from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from agent_assembly.adapters.langchain import AssemblyCallbackHandler
from agent_assembly.adapters.mcp import patch as mcp_patch


@pytest.mark.asyncio
@pytest.mark.integration
async def test_langchain_and_mcp_layers_both_emit_governance_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClientSession:
        def __init__(self) -> None:
            self._server_url = "https://mcp.shared.test"

        async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
            payload = arguments or {}
            return f"mcp:{name}:{payload.get('q', '')}"

    fake_mcp_module = SimpleNamespace(ClientSession=FakeClientSession)
    monkeypatch.setattr(
        mcp_patch.importlib,
        "import_module",
        lambda name: fake_mcp_module if name == "mcp" else (_ for _ in ()).throw(ImportError(name)),
    )

    checks: list[dict[str, object]] = []
    records: list[dict[str, object]] = []

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            checks.append(dict(kwargs))
            return {"status": "allow"}

        async def record_result(self, **kwargs: object) -> None:
            records.append(dict(kwargs))

    callback_handler = AssemblyCallbackHandler(Interceptor())
    patcher = mcp_patch.MCPClientPatch(callback_handler, process_agent_id="agent-chain")
    assert patcher.apply() is True

    callback_handler.on_tool_start(
        serialized={"name": "langchain_tool"},
        input_str="{}",
        run_id=uuid4(),
    )
    result = await FakeClientSession().call_tool("mcp_tool", {"q": "hello"})

    assert result == "mcp:mcp_tool:hello"
    assert len(checks) == 2
    assert checks[0]["serialized"] == {"name": "langchain_tool"}
    assert checks[1]["serialized"] == {"name": "mcp_tool"}
    assert checks[1]["server"] == "https://mcp.shared.test"
    assert len(records) == 1
    assert records[0]["tool_name"] == "mcp_tool"
