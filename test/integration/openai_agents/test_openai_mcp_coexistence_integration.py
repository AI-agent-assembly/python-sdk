from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters.mcp import patch as mcp_patch
from agent_assembly.adapters.openai_agents import patch as openai_patch


@pytest.mark.asyncio
@pytest.mark.integration
async def test_openai_agents_and_mcp_layers_both_emit_governance_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeMCPClientSession:
        def __init__(self) -> None:
            self._server_name = "mcp-from-openai-agent"

        async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
            payload = arguments or {}
            return f"mcp:{name}:{payload.get('q', '')}"

    class FakeToolResult:
        def __init__(self, *, error: str | None = None, output: Any = None) -> None:
            self.error = error
            self.output = output

    class FakeFunctionTool:
        def __init__(self, name: str) -> None:
            self.name = name

        async def __call__(self, ctx: Any, tool_input: Any) -> dict[str, Any]:
            mcp_result = await FakeMCPClientSession().call_tool("mcp_tool", {"q": "hello"})
            return {"name": self.name, "ctx": ctx, "tool_input": tool_input, "mcp_result": mcp_result}

    fake_openai_agents_module = SimpleNamespace(
        FunctionTool=FakeFunctionTool,
        ToolResult=FakeToolResult,
    )
    fake_mcp_module = SimpleNamespace(ClientSession=FakeMCPClientSession)

    monkeypatch.setattr(
        openai_patch.importlib,
        "import_module",
        lambda name: fake_openai_agents_module
        if name == "openai.agents"
        else (_ for _ in ()).throw(ImportError(name)),
    )
    monkeypatch.setattr(
        mcp_patch.importlib,
        "import_module",
        lambda name: fake_mcp_module
        if name == "mcp"
        else (_ for _ in ()).throw(ImportError(name)),
    )

    checks: list[dict[str, object]] = []
    records: list[dict[str, object]] = []

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            checks.append(dict(kwargs))
            return {"status": "allow"}

        async def record_result(self, **kwargs: object) -> None:
            records.append(dict(kwargs))

    interceptor = Interceptor()
    assert openai_patch.OpenAIAgentsPatch(
        callback_handler=interceptor,
        process_agent_id="agent-openai",
    ).apply() is True
    assert mcp_patch.MCPClientPatch(
        callback_handler=interceptor,
        process_agent_id="agent-openai",
    ).apply() is True

    result = await FakeFunctionTool("openai_tool")(SimpleNamespace(agent_id="agent-openai"), {"step": "run"})

    assert result["name"] == "openai_tool"
    assert result["mcp_result"] == "mcp:mcp_tool:hello"
    assert len(checks) == 2
    assert checks[0]["serialized"] == {"name": "openai_tool"}
    assert checks[1]["serialized"] == {"name": "mcp_tool"}
    assert len(records) == 2
