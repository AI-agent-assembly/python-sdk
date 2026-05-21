from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters.google_adk import patch as google_adk_patch
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
