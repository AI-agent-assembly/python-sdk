"""Real-framework governance proof for the Agno adapter.

Unlike ``test/unit/adapters/agno/test_patch.py`` (which drives a *fake*
``agno.tools.function`` module), this test installs the patch over the **real**
``agno.tools.function.FunctionCall`` class and drives an actual tool call the
way Agno does internally — ``Function.from_callable(tool)`` →
``FunctionCall(...).execute()``.

This is the negative control demanded by AAASM-3528: if the patch were a no-op
(the failure mode where an adapter is registered but does not actually gate
tool execution), ``test_real_agno_deny_blocks_tool_body`` would FAIL because the
tool body would run and record its side effect. The test only passes when the
deny genuinely short-circuits the real tool body.

The test is ``importorskip``-guarded on ``agno`` so it runs whenever the
framework is installed (the dev/test dependency group installs it) and is
skipped — not silently passed — when it is not.
"""

from __future__ import annotations

import pytest

pytest.importorskip("agno", reason="agno not installed")

from agno.tools.function import Function, FunctionCall  # noqa: E402

from agent_assembly.adapters.agno import AgnoAdapter  # noqa: E402


@pytest.fixture
def revert_agno_patches() -> object:
    """Ensure the real FunctionCall class is restored after each test."""
    adapters: list[AgnoAdapter] = []
    yield adapters
    for adapter in adapters:
        adapter.unregister_hooks()


@pytest.mark.integration
def test_real_agno_deny_blocks_tool_body(revert_agno_patches: list[AgnoAdapter]) -> None:
    executed: list[int] = []

    def transfer_funds(amount: int) -> str:
        executed.append(amount)
        return f"transferred {amount}"

    class DenyInterceptor:
        _enforce = True

        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "deny", "reason": "policy forbids money movement"}

    adapter = AgnoAdapter()
    revert_agno_patches.append(adapter)
    adapter.register(DenyInterceptor())

    function = Function.from_callable(transfer_funds)
    result = FunctionCall(function=function, arguments={"amount": 1000}).execute()

    # Negative control: a no-op patch would let the body run -> executed == [1000].
    assert executed == []
    assert result.status == "failure"
    assert "[BLOCKED by governance policy]" in str(result.error)
    assert "policy forbids money movement" in str(result.error)


@pytest.mark.integration
def test_real_agno_allow_runs_tool_and_records(revert_agno_patches: list[AgnoAdapter]) -> None:
    executed: list[str] = []
    recorded: list[object] = []

    def lookup_weather(city: str) -> str:
        executed.append(city)
        return f"weather in {city} is sunny"

    class AllowRecording:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "allow"}

        def record_result(self, **kwargs: object) -> None:
            recorded.append(kwargs["result"])

    adapter = AgnoAdapter()
    revert_agno_patches.append(adapter)
    adapter.register(AllowRecording())

    function = Function.from_callable(lookup_weather)
    result = FunctionCall(function=function, arguments={"city": "Tokyo"}).execute()

    assert executed == ["Tokyo"]
    assert result.status == "success"
    assert result.result == "weather in Tokyo is sunny"
    assert len(recorded) == 1


@pytest.mark.integration
def test_real_agno_revert_restores_unguarded_execution(revert_agno_patches: list[AgnoAdapter]) -> None:
    executed: list[int] = []

    def charge(amount: int) -> str:
        executed.append(amount)
        return "charged"

    class DenyInterceptor:
        _enforce = True

        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "deny", "reason": "denied"}

    adapter = AgnoAdapter()
    adapter.register(DenyInterceptor())
    function = Function.from_callable(charge)

    blocked = FunctionCall(function=function, arguments={"amount": 5}).execute()
    assert blocked.status == "failure"
    assert executed == []

    # After revert, the real FunctionCall must run the body unguarded again.
    adapter.unregister_hooks()
    allowed = FunctionCall(function=function, arguments={"amount": 9}).execute()
    assert allowed.status == "success"
    assert executed == [9]


@pytest.mark.integration
def test_real_agno_adapter_detected_and_active() -> None:
    """The registry auto-detects the installed agno adapter and reports it active."""
    from agent_assembly.adapters.registry import AdapterRegistry

    registry = AdapterRegistry()
    try:
        activated = registry.auto_detect()
        assert "agno" in activated
        active_names = {info.name for info in registry.list_active()}
        assert "agno" in active_names
    finally:
        registry.unregister("agno")
