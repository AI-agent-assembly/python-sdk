"""Haystack framework adapter."""

from __future__ import annotations

from agent_assembly.adapters.base import FrameworkAdapter, GovernanceInterceptor
from agent_assembly.adapters.haystack.patch import HaystackPatch


class HaystackAdapter(FrameworkAdapter):
    """Adapter for deepset Haystack 2.x governance hook installation."""

    def __init__(self) -> None:
        self._patch: HaystackPatch | None = None

    def get_framework_name(self) -> str:
        return "haystack"

    def get_supported_versions(self) -> list[str]:
        # Haystack 2.x is the line that exposes the agentic ``Agent`` / ``ToolInvoker``
        # tool-call path and the ``haystack.tools.Tool.invoke`` hook point this adapter
        # patches.  The 1.x line predates that API and is out of scope.
        return [">=2.0.0,<3.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        self._patch = HaystackPatch(interceptor)
        self._patch.apply()

    def unregister_hooks(self) -> None:
        if self._patch is not None:
            self._patch.revert()
            self._patch = None
