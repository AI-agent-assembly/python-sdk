"""Unit tests for the OpenAI Agents FunctionTool governance patch.

These tests target the *real* framework contract (AAASM-3528): the shipped
``agents`` package, whose tools execute via a per-instance ``on_invoke_tool``
coroutine. They use a ``FakeFunctionTool`` shaped like the real dataclass (a
plain ``on_invoke_tool`` instance attribute, no ``__call__``) so that a no-op
patch would FAIL — i.e. these assert governance actually fires.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters.openai_agents import patch as openai_patch


class FakeFunctionTool:
    """Stand-in for ``agents.FunctionTool``.

    Mirrors the real dataclass: tool logic lives in the per-instance
    ``on_invoke_tool`` coroutine assigned in ``__init__``; there is NO
    ``__call__``. Patching the class without wrapping ``on_invoke_tool`` is a
    no-op against this shape.
    """

    def __init__(self, name: str = "fake_openai_tool") -> None:
        self.name = name

        async def _invoke(ctx: Any, input_json: Any) -> dict[str, Any]:
            return {"ctx": ctx, "tool_input": input_json, "name": self.name}

        self.on_invoke_tool = _invoke


@pytest.fixture(autouse=True)
def _reset_function_tool_patch_state() -> Any:
    """Ensure the module-level ``FakeFunctionTool`` class starts and ends each test
    unpatched, since the patch flag lives on the class and would otherwise leak
    one test's callback_handler into the next."""
    openai_patch._revert_function_tool_patch(FakeFunctionTool)
    openai_patch.set_process_agent_id(None)
    yield
    openai_patch._revert_function_tool_patch(FakeFunctionTool)
    openai_patch.set_process_agent_id(None)


def _install_fake_openai_agents_module(monkeypatch: pytest.MonkeyPatch) -> type[FakeFunctionTool]:
    fake_module = SimpleNamespace(FunctionTool=FakeFunctionTool)

    def fake_import_module(module_name: str) -> object:
        if module_name == "agents":
            return fake_module
        raise ImportError(module_name)

    monkeypatch.setattr(openai_patch.importlib, "import_module", fake_import_module)
    monkeypatch.setattr(openai_patch.importlib.util, "find_spec", lambda _package: object())
    return FakeFunctionTool


def test_apply_patches_function_tool_init_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    function_tool_cls = _install_fake_openai_agents_module(monkeypatch)
    patcher = openai_patch.OpenAIAgentsPatch(callback_handler=object(), process_agent_id="agent-1")

    original_init = function_tool_cls.__init__
    assert patcher.apply() is True

    patched_init = function_tool_cls.__init__
    assert patched_init is not original_init
    assert openai_patch._get_process_agent_id() == "agent-1"

    assert patcher.apply() is True
    assert function_tool_cls.__init__ is patched_init

    patcher.revert()


def test_revert_restores_original_init_and_clears_process_agent_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    function_tool_cls = _install_fake_openai_agents_module(monkeypatch)
    original_init = function_tool_cls.__init__
    patcher = openai_patch.OpenAIAgentsPatch(callback_handler=object())

    assert patcher.apply() is True
    assert function_tool_cls.__init__ is not original_init
    patcher.revert()

    assert function_tool_cls.__init__ is original_init
    assert getattr(function_tool_cls, openai_patch._PATCHED_FLAG, False) is False
    assert openai_patch._get_process_agent_id() is None


def test_loader_edge_cases_and_apply_false_when_function_tool_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        openai_patch.importlib,
        "import_module",
        lambda _: (_ for _ in ()).throw(ImportError("agents")),
    )
    monkeypatch.setattr(openai_patch.importlib.util, "find_spec", lambda _package: None)

    assert openai_patch._is_openai_agents_available() is False
    assert openai_patch._load_openai_agents_function_tool_class() is None
    assert openai_patch.OpenAIAgentsPatch(callback_handler=object()).apply() is False

    fake_module = SimpleNamespace(FunctionTool=object())
    monkeypatch.setattr(
        openai_patch.importlib,
        "import_module",
        lambda name: fake_module if name == "agents" else (_ for _ in ()).throw(ImportError(name)),
    )
    monkeypatch.setattr(openai_patch.importlib.util, "find_spec", lambda _package: object())
    assert openai_patch._is_openai_agents_available() is True
    assert openai_patch._load_openai_agents_function_tool_class() is None


@pytest.mark.asyncio
async def test_deny_returns_governance_error_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    function_tool_cls = _install_fake_openai_agents_module(monkeypatch)

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            assert kwargs["tool_name"] == "blocked_tool"
            return {"status": "deny", "reason": "blocked by policy"}

    patcher = openai_patch.OpenAIAgentsPatch(callback_handler=Interceptor())
    assert patcher.apply() is True

    tool = function_tool_cls(name="blocked_tool")
    ctx = SimpleNamespace(agent_id="agent-deny")
    result = await tool.on_invoke_tool(ctx, '{"topic": "finance"}')

    # A no-op patch would return the tool's real output dict — assert it was
    # blocked instead, proving the patch governs the call.
    assert isinstance(result, str)
    assert "blocked by policy" in result


@pytest.mark.asyncio
async def test_revert_makes_governance_a_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After revert, a denied tool runs normally — this is the negative control
    that proves the apply()-state actually intercepts."""
    function_tool_cls = _install_fake_openai_agents_module(monkeypatch)

    class DenyAll:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "deny", "reason": "nope"}

    patcher = openai_patch.OpenAIAgentsPatch(callback_handler=DenyAll())
    assert patcher.apply() is True
    patcher.revert()

    tool = function_tool_cls(name="ungoverned_tool")
    result = await tool.on_invoke_tool(SimpleNamespace(agent_id="a"), "{}")

    assert isinstance(result, dict)
    assert result["name"] == "ungoverned_tool"


@pytest.mark.asyncio
async def test_pending_then_approved_executes_tool_and_records_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    function_tool_cls = _install_fake_openai_agents_module(monkeypatch)
    wait_calls: list[dict[str, object]] = []
    recorded_results: list[dict[str, object]] = []

    class Interceptor:
        pending_tool_approval_timeout_seconds = 23

        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "pending", "reason": "needs approval"}

        async def wait_for_tool_approval(self, **kwargs: object) -> dict[str, str]:
            wait_calls.append(dict(kwargs))
            return {"status": "allow"}

        async def record_result(self, **kwargs: object) -> None:
            recorded_results.append(dict(kwargs))

    patcher = openai_patch.OpenAIAgentsPatch(callback_handler=Interceptor())
    assert patcher.apply() is True

    tool = function_tool_cls(name="approved_tool")
    ctx = SimpleNamespace(agent_id="agent-allow")
    result = await tool.on_invoke_tool(ctx, '{"q": "hello"}')

    assert result["name"] == "approved_tool"
    assert len(wait_calls) == 1
    assert wait_calls[0]["timeout_seconds"] == 23
    assert len(recorded_results) == 1
    assert recorded_results[0]["tool_name"] == "approved_tool"
    assert recorded_results[0]["agent_id"] == "agent-allow"


@pytest.mark.asyncio
async def test_pending_then_denied_returns_governance_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    function_tool_cls = _install_fake_openai_agents_module(monkeypatch)

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "pending", "reason": "needs approval"}

        async def wait_for_tool_approval(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "deny", "reason": "approval rejected"}

    patcher = openai_patch.OpenAIAgentsPatch(callback_handler=Interceptor())
    assert patcher.apply() is True

    tool = function_tool_cls(name="rejected_tool")
    ctx = SimpleNamespace(agent_id="agent-pending-deny")
    result = await tool.on_invoke_tool(ctx, '{"q": "secret"}')

    assert isinstance(result, str)
    assert "approval rejected" in result


@pytest.mark.asyncio
async def test_extracts_agent_id_from_ctx_and_falls_back_to_process_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    function_tool_cls = _install_fake_openai_agents_module(monkeypatch)
    seen_agent_ids: list[str | None] = []

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            seen_agent_ids.append(kwargs.get("agent_id"))  # type: ignore[arg-type]
            return {"status": "allow"}

    patcher = openai_patch.OpenAIAgentsPatch(callback_handler=Interceptor(), process_agent_id="process-agent")
    assert patcher.apply() is True
    tool = function_tool_cls(name="agent_id_tool")

    await tool.on_invoke_tool(SimpleNamespace(agent_id="ctx-agent"), '{"step": 1}')
    await tool.on_invoke_tool(SimpleNamespace(), '{"step": 2}')

    assert seen_agent_ids == ["ctx-agent", "process-agent"]


@pytest.mark.asyncio
async def test_records_tool_result_after_successful_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    function_tool_cls = _install_fake_openai_agents_module(monkeypatch)
    observed_results: list[str] = []

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "allow"}

        async def record_result(self, **kwargs: object) -> None:
            observed_results.append(str(kwargs["result"]))

    patcher = openai_patch.OpenAIAgentsPatch(callback_handler=Interceptor())
    assert patcher.apply() is True

    tool = function_tool_cls(name="record_tool")
    result = await tool.on_invoke_tool(SimpleNamespace(agent_id="agent-rec"), '{"x": 1}')

    assert result["name"] == "record_tool"
    assert len(observed_results) == 1
    assert "record_tool" in observed_results[0]


@pytest.mark.asyncio
async def test_non_governance_error_propagates_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-governance errors (RuntimeError, ValueError, etc.) must propagate.

    This ensures fail-closed security posture: if an unexpected error occurs
    during governance checks, the tool call is blocked rather than allowed
    through. See AAASM-4252.
    """
    function_tool_cls = _install_fake_openai_agents_module(monkeypatch)

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            raise RuntimeError("gateway unavailable")

    patcher = openai_patch.OpenAIAgentsPatch(callback_handler=Interceptor())
    assert patcher.apply() is True

    tool = function_tool_cls(name="fail_closed_tool")
    with pytest.raises(RuntimeError, match="gateway unavailable"):
        await tool.on_invoke_tool(SimpleNamespace(agent_id="agent-fail-closed"), '{"x": 2}')


@pytest.mark.asyncio
async def test_governance_error_allows_fail_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AssemblyError subclasses are handled gracefully (fail-open).

    Governance-specific errors (e.g., transient gateway issues represented as
    GatewayError) are caught and the tool executes. This is intentional: if
    the governance system itself has a known error, we fail-open rather than
    blocking all tool calls. See AAASM-4252.
    """
    from agent_assembly.exceptions import GatewayError

    function_tool_cls = _install_fake_openai_agents_module(monkeypatch)

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            raise GatewayError("gateway temporarily unavailable")

    patcher = openai_patch.OpenAIAgentsPatch(callback_handler=Interceptor())
    assert patcher.apply() is True

    tool = function_tool_cls(name="fail_open_tool")
    result = await tool.on_invoke_tool(SimpleNamespace(agent_id="agent-fail-open"), '{"x": 2}')

    assert result["name"] == "fail_open_tool"


@pytest.mark.asyncio
async def test_value_error_propagates_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ValueError (non-governance) must propagate for fail-closed posture."""
    function_tool_cls = _install_fake_openai_agents_module(monkeypatch)

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            raise ValueError("unexpected")

    patcher = openai_patch.OpenAIAgentsPatch(callback_handler=Interceptor())
    assert patcher.apply() is True

    tool = function_tool_cls(name="strict_tool")
    with pytest.raises(ValueError, match="unexpected"):
        await tool.on_invoke_tool(SimpleNamespace(agent_id="agent-strict"), '{"x": 3}')


@pytest.mark.asyncio
async def test_helper_fallback_branches_for_check_wait_record_and_result_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_openai_agents_module(monkeypatch)

    class Wrapper:
        def __init__(self) -> None:
            self._interceptor = SimpleNamespace()

    # _resolve_governance_target with wrapper
    assert openai_patch._resolve_governance_target(Wrapper()) is not None

    # _invoke_async_tool_check fallback when check method missing
    fallback_check = await openai_patch._invoke_async_tool_check(
        object(),
        tool_name="x",
        tool_input={},
        agent_id=None,
        ctx=SimpleNamespace(),
    )
    assert fallback_check == {"status": "allow"}

    class SyncCheck:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "allow"}

    # _invoke_async_tool_check non-awaitable branch
    sync_check = await openai_patch._invoke_async_tool_check(
        SyncCheck(),
        tool_name="x",
        tool_input={},
        agent_id=None,
        ctx=SimpleNamespace(),
    )
    assert sync_check == {"status": "allow"}

    # _wait_for_async_tool_approval fallback when wait method missing
    fallback_wait = await openai_patch._wait_for_async_tool_approval(
        object(),
        tool_name="x",
        timeout_seconds=1,
        tool_input={},
        agent_id=None,
        ctx=SimpleNamespace(),
    )
    assert fallback_wait["status"] == "deny"  # type: ignore[index]  # fallback branch returns a dict (helper typed object)

    class SyncWait:
        def wait_for_tool_approval(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "allow"}

    # _wait_for_async_tool_approval non-awaitable branch
    sync_wait = await openai_patch._wait_for_async_tool_approval(
        SyncWait(),
        tool_name="x",
        timeout_seconds=1,
        tool_input={},
        agent_id=None,
        ctx=SimpleNamespace(),
    )
    assert sync_wait == {"status": "allow"}

    observed_tool_end: list[str] = []

    class OnToolEndOnly:
        def on_tool_end(self, **kwargs: object) -> None:
            observed_tool_end.append(str(kwargs["output"]))

    # _record_async_tool_result on_tool_end fallback branch
    await openai_patch._record_async_tool_result(
        OnToolEndOnly(),
        tool_name="x",
        tool_input={},
        result={"value": "ok"},
        agent_id=None,
        ctx=SimpleNamespace(),
    )
    assert observed_tool_end


def test_build_tool_deny_error_returns_string_for_both_flows() -> None:
    policy_msg = openai_patch._build_tool_deny_error(
        tool_name="x",
        reason="nope",
        is_pending_rejection=False,
    )
    assert isinstance(policy_msg, str)
    assert "governance policy" in policy_msg
    assert "nope" in policy_msg

    approval_msg = openai_patch._build_tool_deny_error(
        tool_name="x",
        reason=None,
        is_pending_rejection=True,
    )
    assert isinstance(approval_msg, str)
    assert "Approval denied" in approval_msg


def test_apply_and_revert_helpers_cover_non_callable_and_unpatched_branches() -> None:
    class NoInvoke:
        def __init__(self) -> None:
            self.on_invoke_tool = None
            self.name = "no_invoke"

    class NotPatched:
        def __init__(self) -> None:
            async def _invoke(ctx: Any, input_json: Any) -> None:
                del ctx, input_json
                return None

            self.on_invoke_tool = _invoke

    # _wrap_on_invoke_tool early return when on_invoke_tool is not callable
    openai_patch._wrap_on_invoke_tool(NoInvoke(), callback_handler=object())

    # _revert_function_tool_patch early return when patch flag absent
    openai_patch._revert_function_tool_patch(NotPatched)


def test_wrap_on_invoke_tool_is_idempotent_per_instance() -> None:
    class Tool:
        def __init__(self) -> None:
            self.name = "t"

            async def _invoke(ctx: Any, input_json: Any) -> str:
                return "ok"

            self.on_invoke_tool = _invoke

    tool = Tool()
    openai_patch._wrap_on_invoke_tool(tool, callback_handler=object())
    first_wrap = tool.on_invoke_tool
    # Re-wrapping an already-wrapped callable must be a no-op.
    openai_patch._wrap_on_invoke_tool(tool, callback_handler=object())
    assert tool.on_invoke_tool is first_wrap


@pytest.mark.asyncio
async def test_record_result_fallback_awaits_async_on_tool_end() -> None:
    observed: list[str] = []

    class AsyncOnToolEndOnly:
        async def on_tool_end(self, **kwargs: object) -> None:
            observed.append(str(kwargs["output"]))

    await openai_patch._record_async_tool_result(
        AsyncOnToolEndOnly(),
        tool_name="x",
        tool_input={},
        result={"value": "ok"},
        agent_id=None,
        ctx=SimpleNamespace(),
    )

    assert observed
