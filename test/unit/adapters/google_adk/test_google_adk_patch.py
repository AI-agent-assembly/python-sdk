from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters.google_adk import patch as google_adk_patch
from agent_assembly.core.spawn import _SPAWN_CTX, SpawnContext
from agent_assembly.exceptions import PolicyViolationError


class _AllowInterceptor:
    async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
        del kwargs
        return {"status": "allow"}


def _install_fake_google_adk_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> type[Any]:
    class FakeBaseTool:
        name = "fake_tool"

        async def run_async(self, *, args: Any, tool_context: Any, **kwargs: Any) -> dict[str, object]:
            return {"args": args, "tool_context": tool_context, "kwargs": kwargs}

    fake_google_adk_tools = SimpleNamespace(BaseTool=FakeBaseTool)

    def fake_import_module(module_name: str) -> object:
        if module_name == "google.adk.tools":
            return fake_google_adk_tools
        raise ImportError(module_name)

    monkeypatch.setattr(google_adk_patch.importlib, "import_module", fake_import_module)
    return FakeBaseTool


@pytest.mark.asyncio
async def test_apply_patches_run_async_and_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBaseTool = _install_fake_google_adk_modules(monkeypatch)

    patcher = google_adk_patch.GoogleADKPatch(_AllowInterceptor())
    assert patcher.apply() is True
    first_run_ref = FakeBaseTool.run_async

    assert getattr(FakeBaseTool, google_adk_patch._TOOLS_PATCHED_FLAG, False) is True

    # Re-applying is a no-op (idempotent).
    assert patcher.apply() is True
    assert FakeBaseTool.run_async is first_run_ref


def test_revert_restores_run_async_and_clears_process_agent_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeBaseTool = _install_fake_google_adk_modules(monkeypatch)
    original_run_async = FakeBaseTool.run_async
    google_adk_patch.set_process_agent_id("agent-before-revert")

    patcher = google_adk_patch.GoogleADKPatch(_AllowInterceptor())
    assert patcher.apply() is True
    assert FakeBaseTool.run_async is not original_run_async

    patcher.revert()
    assert FakeBaseTool.run_async is original_run_async
    assert getattr(FakeBaseTool, google_adk_patch._TOOLS_PATCHED_FLAG, False) is False
    assert google_adk_patch._get_process_agent_id() is None


def test_apply_returns_false_when_google_adk_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_import_error(module_name: str) -> object:
        raise ImportError(module_name)

    monkeypatch.setattr(google_adk_patch.importlib, "import_module", raise_import_error)
    assert google_adk_patch._load_google_adk_base_tool_class() is None
    assert google_adk_patch.GoogleADKPatch(_AllowInterceptor()).apply() is False


def test_load_base_tool_returns_none_when_attribute_not_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_module = SimpleNamespace(BaseTool=object())

    def return_non_type(module_name: str) -> object:
        if module_name == "google.adk.tools":
            return fake_module
        raise ImportError(module_name)

    monkeypatch.setattr(google_adk_patch.importlib, "import_module", return_non_type)
    assert google_adk_patch._load_google_adk_base_tool_class() is None


@pytest.mark.asyncio
async def test_allow_flow_returns_original_result(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBaseTool = _install_fake_google_adk_modules(monkeypatch)

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "allow"}

    patcher = google_adk_patch.GoogleADKPatch(Interceptor())
    assert patcher.apply() is True

    tool = FakeBaseTool()
    tool_context = SimpleNamespace(
        invocation_context=SimpleNamespace(assembly_agent_id="agent-1", invocation_id="run-1"),
    )
    result = await tool.run_async(args={"step": 1}, tool_context=tool_context)
    assert result["args"] == {"step": 1}


@pytest.mark.asyncio
async def test_deny_flow_raises_policy_violation(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBaseTool = _install_fake_google_adk_modules(monkeypatch)

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "deny", "reason": "blocked by policy"}

    patcher = google_adk_patch.GoogleADKPatch(Interceptor())
    assert patcher.apply() is True

    tool = FakeBaseTool()
    tool_context = SimpleNamespace(invocation_context=None)
    with pytest.raises(PolicyViolationError, match="blocked by governance policy: blocked by policy"):
        await tool.run_async(args={"step": 1}, tool_context=tool_context)


@pytest.mark.asyncio
async def test_pending_flow_routes_through_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBaseTool = _install_fake_google_adk_modules(monkeypatch)

    class Interceptor:
        def __init__(self) -> None:
            self.approval_calls = 0

        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "pending"}

        async def wait_for_tool_approval(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            self.approval_calls += 1
            return {"status": "deny", "reason": "rejected by reviewer"}

    interceptor = Interceptor()
    patcher = google_adk_patch.GoogleADKPatch(interceptor)
    assert patcher.apply() is True

    tool = FakeBaseTool()
    tool_context = SimpleNamespace(invocation_context=None)
    with pytest.raises(PolicyViolationError, match="rejected during approval: rejected by reviewer"):
        await tool.run_async(args={"step": 1}, tool_context=tool_context)
    assert interceptor.approval_calls == 1


def test_resolve_agent_id_falls_back_to_process_default() -> None:
    google_adk_patch.set_process_agent_id("process-agent")
    try:
        assert google_adk_patch._resolve_agent_id(SimpleNamespace(invocation_context=None)) == "process-agent"
        ctx_with_id = SimpleNamespace(invocation_context=SimpleNamespace(assembly_agent_id="ctx-agent"))
        assert google_adk_patch._resolve_agent_id(ctx_with_id) == "ctx-agent"
    finally:
        google_adk_patch.set_process_agent_id(None)


def test_serialize_tool_args_handles_pydantic_mapping_and_other() -> None:
    class _Pydanticish:
        def model_dump(self) -> dict[str, int]:
            return {"a": 1}

    assert google_adk_patch._serialize_tool_args(_Pydanticish()) == {"a": 1}
    assert google_adk_patch._serialize_tool_args({"b": 2}) == {"b": 2}
    assert google_adk_patch._serialize_tool_args("scalar") == {"value": "scalar"}


def _install_fake_google_adk_agent_module(
    monkeypatch: pytest.MonkeyPatch,
    captured: list[SpawnContext | None] | None = None,
) -> type[Any]:
    """Install a fake `google.adk.agents` module whose BaseAgent.run_async is
    an async generator yielding two events, optionally capturing the current
    SpawnContext snapshot at each yield point.
    """

    class FakeBaseAgent:
        async def run_async(self, *args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            if captured is not None:
                captured.append(_SPAWN_CTX.get())
            yield {"event": "e1"}
            if captured is not None:
                captured.append(_SPAWN_CTX.get())
            yield {"event": "e2"}

    fake_module = SimpleNamespace(BaseAgent=FakeBaseAgent)

    def fake_import_module(module_name: str) -> object:
        if module_name == "google.adk.agents":
            return fake_module
        raise ImportError(module_name)

    monkeypatch.setattr(google_adk_patch.importlib, "import_module", fake_import_module)
    return FakeBaseAgent


@pytest.mark.asyncio
async def test_apply_agent_patches_run_async_and_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBaseAgent = _install_fake_google_adk_agent_module(monkeypatch)

    google_adk_patch._apply_agent_run_async_patch(FakeBaseAgent, process_agent_id="parent-1")
    first_ref = FakeBaseAgent.run_async
    assert getattr(FakeBaseAgent, google_adk_patch._AGENT_PATCHED_FLAG, False) is True

    # Re-applying is a no-op.
    google_adk_patch._apply_agent_run_async_patch(FakeBaseAgent, process_agent_id="parent-1")
    assert FakeBaseAgent.run_async is first_ref


def test_revert_agent_patch_restores_run_async_and_clears_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeBaseAgent = _install_fake_google_adk_agent_module(monkeypatch)
    original_run_async = FakeBaseAgent.run_async

    google_adk_patch._apply_agent_run_async_patch(FakeBaseAgent, process_agent_id="parent-1")
    assert FakeBaseAgent.run_async is not original_run_async

    google_adk_patch._revert_agent_run_async_patch(FakeBaseAgent)
    assert FakeBaseAgent.run_async is original_run_async
    assert getattr(FakeBaseAgent, google_adk_patch._AGENT_PATCHED_FLAG, False) is False


def test_revert_agent_patch_is_noop_when_not_patched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeBaseAgent = _install_fake_google_adk_agent_module(monkeypatch)
    original_run_async = FakeBaseAgent.run_async

    # Never applied — revert should not raise or rebind.
    google_adk_patch._revert_agent_run_async_patch(FakeBaseAgent)
    assert FakeBaseAgent.run_async is original_run_async


@pytest.mark.asyncio
async def test_patched_run_async_sets_spawn_context_during_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[SpawnContext | None] = []
    FakeBaseAgent = _install_fake_google_adk_agent_module(monkeypatch, captured=captured)

    google_adk_patch._apply_agent_run_async_patch(FakeBaseAgent, process_agent_id="parent-1")

    agent = FakeBaseAgent()
    events = [event async for event in agent.run_async("ctx")]

    assert events == [{"event": "e1"}, {"event": "e2"}]
    assert len(captured) == 2
    for snapshot in captured:
        assert snapshot is not None
        assert snapshot.spawned_by_tool == "google_adk_agent"
        assert snapshot.parent_agent_id == "parent-1"
        assert snapshot.depth == 1


@pytest.mark.asyncio
async def test_patched_run_async_yields_all_events_from_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeBaseAgent = _install_fake_google_adk_agent_module(monkeypatch)

    google_adk_patch._apply_agent_run_async_patch(FakeBaseAgent, process_agent_id=None)

    agent = FakeBaseAgent()
    events = [event async for event in agent.run_async("ctx")]
    assert events == [{"event": "e1"}, {"event": "e2"}]


def test_load_base_agent_returns_none_when_module_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_import_error(module_name: str) -> object:
        raise ImportError(module_name)

    monkeypatch.setattr(google_adk_patch.importlib, "import_module", raise_import_error)
    assert google_adk_patch._load_google_adk_base_agent_class() is None


def test_load_base_agent_returns_none_when_attribute_not_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_module = SimpleNamespace(BaseAgent=object())

    def return_non_type(module_name: str) -> object:
        if module_name == "google.adk.agents":
            return fake_module
        raise ImportError(module_name)

    monkeypatch.setattr(google_adk_patch.importlib, "import_module", return_non_type)
    assert google_adk_patch._load_google_adk_base_agent_class() is None


@pytest.mark.asyncio
async def test_apply_patches_both_tool_and_agent_when_both_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeBaseTool:
        name = "fake_tool"

        async def run_async(self, *, args: Any, tool_context: Any, **kwargs: Any) -> dict[str, object]:
            del args, tool_context, kwargs
            return {"ran": True}

    class FakeBaseAgent:
        async def run_async(self, *args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            yield {"event": "done"}

    def fake_import_module(module_name: str) -> object:
        if module_name == "google.adk.tools":
            return SimpleNamespace(BaseTool=FakeBaseTool)
        if module_name == "google.adk.agents":
            return SimpleNamespace(BaseAgent=FakeBaseAgent)
        raise ImportError(module_name)

    monkeypatch.setattr(google_adk_patch.importlib, "import_module", fake_import_module)

    patcher = google_adk_patch.GoogleADKPatch(_AllowInterceptor(), process_agent_id="parent-1")
    assert patcher.apply() is True
    assert getattr(FakeBaseTool, google_adk_patch._TOOLS_PATCHED_FLAG, False) is True
    assert getattr(FakeBaseAgent, google_adk_patch._AGENT_PATCHED_FLAG, False) is True

    patcher.revert()
    assert getattr(FakeBaseTool, google_adk_patch._TOOLS_PATCHED_FLAG, False) is False
    assert getattr(FakeBaseAgent, google_adk_patch._AGENT_PATCHED_FLAG, False) is False


def test_apply_proceeds_with_only_tool_when_agent_module_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeBaseTool:
        name = "fake_tool"

        async def run_async(self, *, args: Any, tool_context: Any, **kwargs: Any) -> dict[str, object]:
            del args, tool_context, kwargs
            return {"ran": True}

    def fake_import_module(module_name: str) -> object:
        if module_name == "google.adk.tools":
            return SimpleNamespace(BaseTool=FakeBaseTool)
        raise ImportError(module_name)

    monkeypatch.setattr(google_adk_patch.importlib, "import_module", fake_import_module)

    patcher = google_adk_patch.GoogleADKPatch(_AllowInterceptor())
    # Tool present, agent missing — apply still succeeds via the tool branch.
    assert patcher.apply() is True
    assert getattr(FakeBaseTool, google_adk_patch._TOOLS_PATCHED_FLAG, False) is True

    patcher.revert()
    assert getattr(FakeBaseTool, google_adk_patch._TOOLS_PATCHED_FLAG, False) is False


def _install_fake_google_adk_with_function_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[type[Any], type[Any]]:
    """Model ADK 1.x: a concrete ``FunctionTool`` subclass that OVERRIDES
    ``run_async``, so a patch on ``BaseTool.run_async`` alone never runs for it.
    """

    class FakeBaseTool:
        name = "base_tool"

        async def run_async(self, *, args: Any, tool_context: Any, **kwargs: Any) -> dict[str, object]:
            del kwargs
            return {"who": "base", "args": args, "tool_context": tool_context}

    class FakeFunctionTool(FakeBaseTool):
        name = "function_tool"

        # Concrete subclass overrides run_async (its own __dict__ entry).
        async def run_async(self, *, args: Any, tool_context: Any, **kwargs: Any) -> dict[str, object]:
            del kwargs
            return {"who": "function", "args": args, "tool_context": tool_context}

    fake_module = SimpleNamespace(BaseTool=FakeBaseTool, FunctionTool=FakeFunctionTool)

    def fake_import_module(module_name: str) -> object:
        if module_name == "google.adk.tools":
            return fake_module
        raise ImportError(module_name)

    monkeypatch.setattr(google_adk_patch.importlib, "import_module", fake_import_module)
    return FakeBaseTool, FakeFunctionTool


def test_load_concrete_tool_classes_finds_run_async_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeBaseTool, FakeFunctionTool = _install_fake_google_adk_with_function_tool(monkeypatch)

    concrete = google_adk_patch._load_google_adk_concrete_tool_classes(FakeBaseTool)

    # The base class itself is excluded; the overriding subclass is included.
    assert FakeFunctionTool in concrete
    assert FakeBaseTool not in concrete


@pytest.mark.asyncio
async def test_apply_patches_concrete_function_tool_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeBaseTool, FakeFunctionTool = _install_fake_google_adk_with_function_tool(monkeypatch)

    patcher = google_adk_patch.GoogleADKPatch(_AllowInterceptor())
    assert patcher.apply() is True

    # Both the base and the concrete override are patched.
    assert getattr(FakeBaseTool, google_adk_patch._TOOLS_PATCHED_FLAG, False) is True
    assert getattr(FakeFunctionTool, google_adk_patch._TOOLS_PATCHED_FLAG, False) is True


@pytest.mark.asyncio
async def test_function_tool_override_is_intercepted_on_deny(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, FakeFunctionTool = _install_fake_google_adk_with_function_tool(monkeypatch)

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "deny", "reason": "blocked subclass"}

    patcher = google_adk_patch.GoogleADKPatch(Interceptor())
    assert patcher.apply() is True

    tool = FakeFunctionTool()
    tool_context = SimpleNamespace(invocation_context=None)
    # Governance runs on the SUBCLASS run_async, not just the base.
    with pytest.raises(PolicyViolationError, match="blocked by governance policy: blocked subclass"):
        await tool.run_async(args={"step": 1}, tool_context=tool_context)


@pytest.mark.asyncio
async def test_revert_restores_concrete_function_tool_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeBaseTool, FakeFunctionTool = _install_fake_google_adk_with_function_tool(monkeypatch)
    original_base = FakeBaseTool.run_async
    original_function = FakeFunctionTool.run_async

    patcher = google_adk_patch.GoogleADKPatch(_AllowInterceptor())
    assert patcher.apply() is True
    assert FakeFunctionTool.run_async is not original_function

    patcher.revert()
    assert FakeBaseTool.run_async is original_base
    assert FakeFunctionTool.run_async is original_function
    assert getattr(FakeBaseTool, google_adk_patch._TOOLS_PATCHED_FLAG, False) is False
    assert getattr(FakeFunctionTool, google_adk_patch._TOOLS_PATCHED_FLAG, False) is False
