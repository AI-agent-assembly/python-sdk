"""Agno (formerly Phidata) framework adapter.

Governs Agno agents at the SDK layer by patching the framework's single
function-tool execution chokepoint (``FunctionCall.execute`` / ``aexecute``).
See ``agent_assembly.adapters.agno.patch`` for the hook-point rationale.
"""

from __future__ import annotations

from agent_assembly.adapters.agno.patch import AgnoPatch
from agent_assembly.adapters.base import FrameworkAdapter, GovernanceInterceptor


class AgnoAdapter(FrameworkAdapter):
    """Adapter for Agno (pip ``agno``) framework governance hook installation."""

    def __init__(self) -> None:
        self._patch: AgnoPatch | None = None

    def get_framework_name(self) -> str:
        return "agno"

    def get_supported_versions(self) -> list[str]:
        return [">=2.0.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        self._patch = AgnoPatch(interceptor)
        self._patch.apply()

    def unregister_hooks(self) -> None:
        if self._patch is not None:
            self._patch.revert()
            self._patch = None
