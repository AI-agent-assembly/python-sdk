"""MCP client patch module."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from typing import Any


@dataclass(slots=True)
class MCPClientPatch:
    """Patch placeholder for MCP client interception."""

    callback_handler: Any

    def apply(self) -> bool:
        _ = self.callback_handler
        return _is_mcp_available()

    def revert(self) -> None:
        return None


def _is_mcp_available() -> bool:
    return importlib.util.find_spec("mcp") is not None
