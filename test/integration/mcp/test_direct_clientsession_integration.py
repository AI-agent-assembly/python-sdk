from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters.mcp import patch as mcp_patch
from agent_assembly.exceptions import MCPToolBlockedError


@pytest.mark.asyncio
@pytest.mark.integration
async def test_direct_mcp_clientsession_blocks_mid_flow_and_allows_followup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClientSession:
        def __init__(self) -> None:
            self._server_name = "direct-mcp-server"

        async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
            payload = arguments or {}
            return f"ok:{name}:{payload.get('step', 'none')}"

    fake_mcp_module = SimpleNamespace(ClientSession=FakeClientSession)
    monkeypatch.setattr(
        mcp_patch.importlib,
        "import_module",
        lambda name: fake_mcp_module if name == "mcp" else (_ for _ in ()).throw(ImportError(name)),
    )

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            if kwargs.get("tool_name") == "blocked_tool":
                return {"status": "deny", "reason": "blocked by policy"}
            return {"status": "allow"}

    patcher = mcp_patch.MCPClientPatch(Interceptor(), process_agent_id="agent-custom")
    assert patcher.apply() is True

    session = FakeClientSession()
    with pytest.raises(MCPToolBlockedError, match="blocked by governance policy: blocked by policy"):
        await session.call_tool("blocked_tool", {"step": "one"})

    safe_result = await session.call_tool("safe_tool", {"step": "two"})
    assert safe_result == "ok:safe_tool:two"
