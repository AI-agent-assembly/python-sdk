"""Smolagents framework adapter."""

from __future__ import annotations

from agent_assembly.adapters.base import FrameworkAdapter, GovernanceInterceptor
from agent_assembly.adapters.smolagents.patch import SmolagentsPatch


class SmolagentsAdapter(FrameworkAdapter):
    """Adapter for Smolagents (Hugging Face) governance hook installation."""

    def __init__(self) -> None:
        self._patch: SmolagentsPatch | None = None

    def get_framework_name(self) -> str:
        return "smolagents"

    def get_supported_versions(self) -> list[str]:
        # Tool.__call__ -> self.forward has been the tool-execution chokepoint
        # since the 1.x line; pin the lower bound to the first stable 1.0 release.
        return [">=1.0.0,<2.0.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        self._patch = SmolagentsPatch(interceptor)
        self._patch.apply()

    def unregister_hooks(self) -> None:
        if self._patch is not None:
            self._patch.revert()
            self._patch = None
