from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters.google_adk import patch as google_adk_patch
from agent_assembly.exceptions import PolicyViolationError


@pytest.mark.asyncio
@pytest.mark.integration
async def test_google_adk_two_tool_flow_continues_after_blocked_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeBaseTool:
        def __init__(self, name: str, result: str) -> None:
            self.name = name
            self._result = result

        async def run_async(self, *, args: Any, tool_context: Any, **kwargs: Any) -> str:
            del args, tool_context, kwargs
            return self._result

    fake_google_adk_tools = SimpleNamespace(BaseTool=FakeBaseTool)

    def fake_import_module(module_name: str) -> object:
        if module_name == "google.adk.tools":
            return fake_google_adk_tools
        raise ImportError(module_name)

    monkeypatch.setattr(google_adk_patch.importlib, "import_module", fake_import_module)

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            if kwargs.get("tool_name") == "blocked_tool":
                return {"status": "deny", "reason": "blocked by policy"}
            return {"status": "allow"}

    patcher = google_adk_patch.GoogleADKPatch(Interceptor())
    assert patcher.apply() is True

    tool_context = SimpleNamespace(
        invocation_context=SimpleNamespace(assembly_agent_id="agent-1", invocation_id="run-main"),
    )
    blocked_tool = FakeBaseTool("blocked_tool", "should-not-run")
    safe_tool = FakeBaseTool("safe_tool", "ok:safe_tool")

    with pytest.raises(PolicyViolationError, match="blocked by governance policy: blocked by policy"):
        await blocked_tool.run_async(args={"step": 1}, tool_context=tool_context)

    safe_result = await safe_tool.run_async(args={"step": 2}, tool_context=tool_context)
    assert safe_result == "ok:safe_tool"


@pytest.mark.integration
def test_google_adk_real_base_tool_class_patch_path_when_available() -> None:
    google_adk_tools = pytest.importorskip("google.adk.tools")
    tool_cls = google_adk_tools.BaseTool

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "allow"}

    patcher = google_adk_patch.GoogleADKPatch(Interceptor())
    try:
        assert patcher.apply() is True
        assert getattr(tool_cls, google_adk_patch._TOOLS_PATCHED_FLAG, False) is True
    finally:
        patcher.revert()
    assert getattr(tool_cls, google_adk_patch._TOOLS_PATCHED_FLAG, False) is False
