from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters.pydantic_ai import patch as pydantic_ai_patch
from agent_assembly.exceptions import PolicyViolationError


@pytest.mark.asyncio
@pytest.mark.integration
async def test_pydantic_ai_two_tool_flow_continues_after_blocked_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeTool:
        def __init__(self, name: str, result: str) -> None:
            self.name = name
            self._result = result

        async def _run(self, ctx: Any, args: Any, **kwargs: Any) -> str:
            del ctx, args, kwargs
            return self._result

    fake_pydantic_ai_tools = SimpleNamespace(Tool=FakeTool)

    def fake_import_module(module_name: str) -> object:
        if module_name == "pydantic_ai.tools":
            return fake_pydantic_ai_tools
        raise ImportError(module_name)

    monkeypatch.setattr(pydantic_ai_patch.importlib, "import_module", fake_import_module)

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            if kwargs.get("tool_name") == "blocked_tool":
                return {"status": "deny", "reason": "blocked by policy"}
            return {"status": "allow"}

    patcher = pydantic_ai_patch.PydanticAIPatch(Interceptor())
    assert patcher.apply() is True

    ctx = SimpleNamespace(deps=SimpleNamespace(assembly_agent_id="agent-1"), run_id="run-main")
    blocked_tool = FakeTool("blocked_tool", "should-not-run")
    safe_tool = FakeTool("safe_tool", "ok:safe_tool")

    with pytest.raises(PolicyViolationError, match="blocked by governance policy: blocked by policy"):
        await blocked_tool._run(ctx, {"step": 1})

    safe_result = await safe_tool._run(ctx, {"step": 2})
    assert safe_result == "ok:safe_tool"


@pytest.mark.integration
def test_pydantic_ai_real_tool_class_patch_path_when_available() -> None:
    pydantic_ai_tools = pytest.importorskip("pydantic_ai.tools")
    tool_cls = pydantic_ai_tools.Tool

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "allow"}

    patcher = pydantic_ai_patch.PydanticAIPatch(Interceptor())
    assert patcher.apply() is True
    assert getattr(tool_cls, pydantic_ai_patch._TOOLS_PATCHED_FLAG, False) is True
