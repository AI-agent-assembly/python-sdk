"""Microsoft Agent Framework adapter."""

from __future__ import annotations

import importlib.util

from agent_assembly.adapters.base import FrameworkAdapter, GovernanceInterceptor
from agent_assembly.adapters.microsoft_agent_framework.patch import (
    MicrosoftAgentFrameworkPatch,
)


class MicrosoftAgentFrameworkAdapter(FrameworkAdapter):
    """Adapter for Microsoft Agent Framework governance hook installation."""

    def __init__(self, *, process_agent_id: str | None = None) -> None:
        self._process_agent_id = process_agent_id
        self._patch: MicrosoftAgentFrameworkPatch | None = None

    @property
    def process_agent_id(self) -> str | None:
        return self._process_agent_id

    @process_agent_id.setter
    def process_agent_id(self, value: str | None) -> None:
        self._process_agent_id = value

    def get_framework_name(self) -> str:
        return "microsoft_agent_framework"

    def get_supported_versions(self) -> list[str]:
        # Microsoft Agent Framework reached its first stable line at 1.x
        # (``agent-framework`` / ``agent-framework-core`` 1.9.0 at time of
        # writing). Pin to the 1.x major; the 2.x surface is unverified.
        return [">=1.0.0,<2.0"]

    def is_available(self) -> bool:
        """Detect the importable ``agent_framework`` package.

        WHY override (AAASM-3528 lesson): the framework name
        (``microsoft_agent_framework``) deliberately differs from the importable
        module (``agent_framework``). The base ``is_available`` imports
        ``get_framework_name()``, which would never resolve here and make the
        adapter silently report unavailable. Detect the real top-level module so
        the hook genuinely activates when the framework is installed.
        """
        try:
            return importlib.util.find_spec("agent_framework") is not None
        except (ImportError, ValueError):
            return False

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        self._patch = MicrosoftAgentFrameworkPatch(
            callback_handler=interceptor,
            process_agent_id=self._process_agent_id,
        )
        self._patch.apply()

    def unregister_hooks(self) -> None:
        if self._patch is not None:
            self._patch.revert()
            self._patch = None
