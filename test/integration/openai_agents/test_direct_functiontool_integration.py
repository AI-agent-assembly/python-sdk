from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters.openai_agents import patch as openai_patch


@pytest.mark.asyncio
@pytest.mark.integration
async def test_direct_openai_agents_functiontool_blocks_then_allows_followup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeToolResult:
        def __init__(self, *, error: str | None = None, output: Any = None) -> None:
            self.error = error
            self.output = output

    class FakeFunctionTool:
        def __init__(self, name: str) -> None:
            self.name = name

        async def __call__(self, ctx: Any, tool_input: Any) -> dict[str, Any]:
            return {"name": self.name, "ctx": ctx, "tool_input": tool_input}

    fake_openai_agents_module = SimpleNamespace(
        FunctionTool=FakeFunctionTool,
        ToolResult=FakeToolResult,
    )
    monkeypatch.setattr(
        openai_patch.importlib,
        "import_module",
        lambda name: fake_openai_agents_module
        if name == "openai.agents"
        else (_ for _ in ()).throw(ImportError(name)),
    )

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            if kwargs.get("tool_name") == "blocked_tool":
                return {"status": "deny", "reason": "blocked by policy"}
            return {"status": "allow"}

    patcher = openai_patch.OpenAIAgentsPatch(callback_handler=Interceptor(), process_agent_id="agent-oa")
    assert patcher.apply() is True

    blocked = await FakeFunctionTool("blocked_tool")(SimpleNamespace(agent_id="agent-oa"), {"step": 1})
    safe = await FakeFunctionTool("safe_tool")(SimpleNamespace(agent_id="agent-oa"), {"step": 2})

    assert isinstance(blocked, FakeToolResult)
    assert isinstance(blocked.error, str)
    assert "blocked by policy" in blocked.error
    assert safe["name"] == "safe_tool"
