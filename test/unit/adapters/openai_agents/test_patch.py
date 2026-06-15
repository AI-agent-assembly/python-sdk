from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters.openai_agents import patch as openai_patch


def _install_fake_openai_agents_module(monkeypatch: pytest.MonkeyPatch) -> tuple[type[Any], type[Any]]:
    class FakeToolResult:
        def __init__(self, *, error: str | None = None, output: Any = None) -> None:
            self.error = error
            self.output = output

    class FakeFunctionTool:
        def __init__(self, name: str = "fake_openai_tool") -> None:
            self.name = name

        async def __call__(self, ctx: Any, tool_input: Any) -> dict[str, Any]:
            return {"ctx": ctx, "tool_input": tool_input, "name": self.name}

    fake_module = SimpleNamespace(FunctionTool=FakeFunctionTool, ToolResult=FakeToolResult)

    def fake_import_module(module_name: str) -> object:
        if module_name == "openai.agents":
            return fake_module
        raise ImportError(module_name)

    monkeypatch.setattr(openai_patch.importlib, "import_module", fake_import_module)
    monkeypatch.setattr(openai_patch.importlib.util, "find_spec", lambda package: object())
    return FakeFunctionTool, FakeToolResult


def test_apply_patches_functiontool_call_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    function_tool_cls, _ = _install_fake_openai_agents_module(monkeypatch)
    patcher = openai_patch.OpenAIAgentsPatch(callback_handler=object(), process_agent_id="agent-1")

    original_call = function_tool_cls.__call__
    assert patcher.apply() is True

    patched_call = function_tool_cls.__call__
    assert patched_call is not original_call
    assert openai_patch._get_process_agent_id() == "agent-1"

    assert patcher.apply() is True
    assert function_tool_cls.__call__ is patched_call


def test_revert_restores_original_functiontool_call_and_clears_process_agent_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    function_tool_cls, _ = _install_fake_openai_agents_module(monkeypatch)
    original_call = function_tool_cls.__call__
    patcher = openai_patch.OpenAIAgentsPatch(callback_handler=object())

    assert patcher.apply() is True
    assert function_tool_cls.__call__ is not original_call
    patcher.revert()

    assert function_tool_cls.__call__ is original_call
    assert getattr(function_tool_cls, openai_patch._PATCHED_FLAG, False) is False
    assert openai_patch._get_process_agent_id() is None


def test_loader_edge_cases_and_apply_false_when_functiontool_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        openai_patch.importlib,
        "import_module",
        lambda _: (_ for _ in ()).throw(ImportError("openai.agents")),
    )
    monkeypatch.setattr(openai_patch.importlib.util, "find_spec", lambda package: None)

    assert openai_patch._is_openai_agents_available() is False
    assert openai_patch._load_openai_agents_function_tool_class() is None
    assert openai_patch.OpenAIAgentsPatch(callback_handler=object()).apply() is False

    fake_module = SimpleNamespace(FunctionTool=object())
    monkeypatch.setattr(
        openai_patch.importlib,
        "import_module",
        lambda name: fake_module if name == "openai.agents" else (_ for _ in ()).throw(ImportError(name)),
    )
    monkeypatch.setattr(openai_patch.importlib.util, "find_spec", lambda package: object())
    assert openai_patch._is_openai_agents_available() is True
    assert openai_patch._load_openai_agents_function_tool_class() is None


@pytest.mark.asyncio
async def test_deny_returns_toolresult_error_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    function_tool_cls, tool_result_cls = _install_fake_openai_agents_module(monkeypatch)

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            assert kwargs["tool_name"] == "blocked_tool"
            return {"status": "deny", "reason": "blocked by policy"}

    patcher = openai_patch.OpenAIAgentsPatch(callback_handler=Interceptor())
    assert patcher.apply() is True

    tool = function_tool_cls(name="blocked_tool")
    ctx = SimpleNamespace(agent_id="agent-deny")
    result = await tool(ctx, {"topic": "finance"})

    assert isinstance(result, tool_result_cls)
    assert isinstance(result.error, str)
    assert "blocked by policy" in result.error


@pytest.mark.asyncio
async def test_pending_then_approved_executes_tool_and_records_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    function_tool_cls, _ = _install_fake_openai_agents_module(monkeypatch)
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
    result = await tool(ctx, {"q": "hello"})

    assert result["name"] == "approved_tool"
    assert len(wait_calls) == 1
    assert wait_calls[0]["timeout_seconds"] == 23
    assert len(recorded_results) == 1
    assert recorded_results[0]["tool_name"] == "approved_tool"
    assert recorded_results[0]["agent_id"] == "agent-allow"


@pytest.mark.asyncio
async def test_pending_then_denied_returns_toolresult_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    function_tool_cls, tool_result_cls = _install_fake_openai_agents_module(monkeypatch)

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
    result = await tool(ctx, {"q": "secret"})

    assert isinstance(result, tool_result_cls)
    assert isinstance(result.error, str)
    assert "approval rejected" in result.error


@pytest.mark.asyncio
async def test_extracts_agent_id_from_ctx_and_falls_back_to_process_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    function_tool_cls, _ = _install_fake_openai_agents_module(monkeypatch)
    seen_agent_ids: list[str | None] = []

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            seen_agent_ids.append(kwargs.get("agent_id"))  # type: ignore[arg-type]
            return {"status": "allow"}

    patcher = openai_patch.OpenAIAgentsPatch(callback_handler=Interceptor(), process_agent_id="process-agent")
    assert patcher.apply() is True
    tool = function_tool_cls(name="agent_id_tool")

    await tool(SimpleNamespace(agent_id="ctx-agent"), {"step": 1})
    await tool(SimpleNamespace(), {"step": 2})

    assert seen_agent_ids == ["ctx-agent", "process-agent"]


@pytest.mark.asyncio
async def test_records_tool_result_after_successful_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    function_tool_cls, _ = _install_fake_openai_agents_module(monkeypatch)
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
    result = await tool(SimpleNamespace(agent_id="agent-rec"), {"x": 1})

    assert result["name"] == "record_tool"
    assert len(observed_results) == 1
    assert "record_tool" in observed_results[0]


@pytest.mark.asyncio
async def test_gateway_error_uses_fail_open_and_executes_original_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    function_tool_cls, _ = _install_fake_openai_agents_module(monkeypatch)

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            raise RuntimeError("gateway unavailable")

    patcher = openai_patch.OpenAIAgentsPatch(callback_handler=Interceptor())
    assert patcher.apply() is True

    tool = function_tool_cls(name="fail_open_tool")
    result = await tool(SimpleNamespace(agent_id="agent-fail-open"), {"x": 2})

    assert result["name"] == "fail_open_tool"


@pytest.mark.asyncio
async def test_non_governance_error_is_reraised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    function_tool_cls, _ = _install_fake_openai_agents_module(monkeypatch)

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            raise ValueError("unexpected")

    monkeypatch.setattr(openai_patch, "_is_governance_error", lambda error: False)

    patcher = openai_patch.OpenAIAgentsPatch(callback_handler=Interceptor())
    assert patcher.apply() is True

    tool = function_tool_cls(name="strict_tool")
    with pytest.raises(ValueError, match="unexpected"):
        await tool(SimpleNamespace(agent_id="agent-strict"), {"x": 3})


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

    class FailingToolResult:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            raise RuntimeError("cannot build")

    fake_module = SimpleNamespace(FunctionTool=object(), ToolResult=FailingToolResult)
    monkeypatch.setattr(
        openai_patch.importlib,
        "import_module",
        lambda name: fake_module if name == "openai.agents" else (_ for _ in ()).throw(ImportError(name)),
    )

    # _build_tool_result_error fallback dict branch
    fallback_result = openai_patch._build_tool_result_error(
        tool_name="x",
        reason="nope",
        is_pending_rejection=False,
    )
    assert isinstance(fallback_result, dict)
    assert "error" in fallback_result


def test_apply_and_revert_helpers_cover_non_callable_and_unpatched_branches() -> None:
    class NoCallable:
        __call__ = None

    class NotPatched:
        async def __call__(self, ctx: Any, tool_input: Any) -> None:
            del ctx, tool_input
            return None

    # _apply_function_tool_call_patch early return when __call__ is not callable
    openai_patch._apply_function_tool_call_patch(NoCallable, callback_handler=object())

    # _revert_function_tool_call_patch early return when patch flag absent
    openai_patch._revert_function_tool_call_patch(NotPatched)


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
