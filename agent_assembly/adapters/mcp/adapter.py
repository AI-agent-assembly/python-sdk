"""MCP framework adapter."""

from __future__ import annotations

from agent_assembly.adapters.base import FrameworkAdapter, GovernanceInterceptor
from agent_assembly.adapters.mcp.patch import MCPClientPatch


class MCPAdapter(FrameworkAdapter):
    """Adapter for MCP client governance hook installation."""

    def __init__(self, *, process_agent_id: str | None = None) -> None:
        self._process_agent_id = process_agent_id
        self._patch: MCPClientPatch | None = None

    @property
    def process_agent_id(self) -> str | None:
        return self._process_agent_id

    @process_agent_id.setter
    def process_agent_id(self, value: str | None) -> None:
        self._process_agent_id = value

    def get_framework_name(self) -> str:
        return "mcp"

    def get_supported_versions(self) -> list[str]:
        return [">=1.0.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        self._patch = MCPClientPatch(
            callback_handler=interceptor,
            process_agent_id=self._process_agent_id,
        )
        self._patch.apply()

    def unregister_hooks(self) -> None:
        if self._patch is not None:
            self._patch.revert()
            self._patch = None
