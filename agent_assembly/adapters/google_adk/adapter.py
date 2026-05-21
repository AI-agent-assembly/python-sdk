"""Google ADK framework adapter."""

from __future__ import annotations

import importlib.util

from agent_assembly.adapters.base import FrameworkAdapter, GovernanceInterceptor
from agent_assembly.adapters.google_adk.patch import GoogleADKPatch


class GoogleADKAdapter(FrameworkAdapter):
    """Adapter for Google ADK framework governance hook installation."""

    def __init__(self) -> None:
        self._process_agent_id: str | None = None
        self._patch: GoogleADKPatch | None = None

    @property
    def process_agent_id(self) -> str | None:
        return self._process_agent_id

    @process_agent_id.setter
    def process_agent_id(self, value: str | None) -> None:
        self._process_agent_id = value

    def get_framework_name(self) -> str:
        return "google_adk"

    def get_supported_versions(self) -> list[str]:
        return [">=1.0.0,<2.0"]

    def is_available(self) -> bool:
        # Framework name (`google_adk`) does not match the importable module
        # path (`google.adk`).  `find_spec` raises `ModuleNotFoundError` when
        # the parent `google` namespace package is absent, so guard for it.
        try:
            return importlib.util.find_spec("google.adk") is not None
        except (ImportError, ValueError):
            return False

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        self._patch = GoogleADKPatch(
            callback_handler=interceptor,
            process_agent_id=self._process_agent_id,
        )
        self._patch.apply()

    def unregister_hooks(self) -> None:
        if self._patch is not None:
            self._patch.revert()
            self._patch = None
