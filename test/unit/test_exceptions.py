from __future__ import annotations

import agent_assembly
import agent_assembly.exceptions as exceptions
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


# AAASM-5056: these two classes are documented as top-level imports; guard
# against them silently dropping out of the package's public export tables.
def test_policy_violation_and_op_terminated_are_top_level_exports() -> None:
    from agent_assembly import OpTerminatedError, PolicyViolationError

    assert "PolicyViolationError" in agent_assembly.__all__
    assert "OpTerminatedError" in agent_assembly.__all__
    assert PolicyViolationError is exceptions.PolicyViolationError
    assert OpTerminatedError is exceptions.OpTerminatedError
