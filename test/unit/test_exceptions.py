from __future__ import annotations

from agent_assembly import MCPToolBlockedError


def test_mcp_tool_blocked_error_exposes_tool_and_server_metadata() -> None:
    error = MCPToolBlockedError(
        "blocked",
        tool_name="search_docs",
        server="https://mcp.example.test",
    )

    assert str(error) == "blocked"
    assert error.tool_name == "search_docs"
    assert error.server == "https://mcp.example.test"
