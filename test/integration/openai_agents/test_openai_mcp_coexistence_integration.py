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

    class FakeFunctionTool:
        """Shaped like ``agents.FunctionTool``: per-instance ``on_invoke_tool``."""

        def __init__(self, name: str) -> None:
            self.name = name

            async def _invoke(ctx: Any, tool_input: Any) -> dict[str, Any]:
                mcp_result = await FakeMCPClientSession().call_tool("mcp_tool", {"q": "hello"})
                return {"name": self.name, "ctx": ctx, "tool_input": tool_input, "mcp_result": mcp_result}

            self.on_invoke_tool = _invoke

    fake_openai_agents_module = SimpleNamespace(FunctionTool=FakeFunctionTool)
    fake_mcp_module = SimpleNamespace(ClientSession=FakeMCPClientSession)

    def fake_import_module(name: str) -> object:
        if name == "agents":
            return fake_openai_agents_module
        if name == "mcp":
            return fake_mcp_module
        raise ImportError(name)

    monkeypatch.setattr(openai_patch.importlib, "import_module", fake_import_module)
    monkeypatch.setattr(mcp_patch.importlib, "import_module", fake_import_module)

    checks: list[dict[str, object]] = []
    records: list[dict[str, object]] = []

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            checks.append(dict(kwargs))
            return {"status": "allow"}

        async def record_result(self, **kwargs: object) -> None:
            records.append(dict(kwargs))

    interceptor = Interceptor()
    assert (
        openai_patch.OpenAIAgentsPatch(
            callback_handler=interceptor,
            process_agent_id="agent-openai",
        ).apply()
        is True
    )
    assert (
        mcp_patch.MCPClientPatch(
            callback_handler=interceptor,
            process_agent_id="agent-openai",
        ).apply()
        is True
    )

    tool = FakeFunctionTool("openai_tool")
    result = await tool.on_invoke_tool(SimpleNamespace(agent_id="agent-openai"), {"step": "run"})

    assert result["name"] == "openai_tool"
    assert result["mcp_result"] == "mcp:mcp_tool:hello"
    assert len(checks) == 2
    assert checks[0]["serialized"] == {"name": "openai_tool"}
    assert checks[1]["serialized"] == {"name": "mcp_tool"}
    assert len(records) == 2
