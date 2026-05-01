"""LangGraph framework adapter."""

from __future__ import annotations

from agent_assembly.adapters.base import FrameworkAdapter, GovernanceInterceptor
from agent_assembly.adapters.langgraph.patch import LangGraphPatch


class LangGraphAdapter(FrameworkAdapter):
    """Adapter for LangGraph framework governance hook installation."""

    def __init__(self) -> None:
        self._patch: LangGraphPatch | None = None

    def get_framework_name(self) -> str:
        return "langgraph"

    def get_supported_versions(self) -> list[str]:
        return [">=0.1.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        self._patch = LangGraphPatch(interceptor)
        self._patch.apply()

    def unregister_hooks(self) -> None:
        if self._patch is not None:
            self._patch.revert()
            self._patch = None
