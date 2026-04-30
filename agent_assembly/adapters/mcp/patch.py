"""MCP client patch module."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import importlib.util
import inspect
from typing import Any

_ORIGINAL_CALL_TOOL = "_agent_assembly_original_mcp_call_tool"
_PATCHED_FLAG = "_agent_assembly_mcp_clientsession_patched"
_PROCESS_AGENT_ID: str | None = None
_MAX_AUDIT_RESULT_CHARS = 2000


@dataclass(slots=True)
class MCPClientPatch:
    """Patch placeholder for MCP client interception."""

    callback_handler: Any
    process_agent_id: str | None = None

    def apply(self) -> bool:
        set_process_agent_id(self.process_agent_id)
        _ = self.callback_handler
        return _is_mcp_available()

    def revert(self) -> None:
        set_process_agent_id(None)
        return None


def _is_mcp_available() -> bool:
    return importlib.util.find_spec("mcp") is not None


def set_process_agent_id(agent_id: str | None) -> None:
    global _PROCESS_AGENT_ID
    _PROCESS_AGENT_ID = agent_id


def _get_process_agent_id() -> str | None:
    if isinstance(_PROCESS_AGENT_ID, str) and _PROCESS_AGENT_ID:
        return _PROCESS_AGENT_ID
    return None
