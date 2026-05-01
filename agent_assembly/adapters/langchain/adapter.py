"""LangChain framework adapter."""

from __future__ import annotations

from typing import Any

from agent_assembly.adapters.base import FrameworkAdapter, GovernanceInterceptor
from agent_assembly.adapters.langchain.patch import LangChainPatch
from agent_assembly.adapters.langchain.runtime import get_active_callback_handler


class LangChainAdapter(FrameworkAdapter):
    """Adapter for LangChain framework governance hook installation."""

    def __init__(self, *, process_agent_id: str | None = None) -> None:
        self._process_agent_id = process_agent_id
        self._patch: LangChainPatch | None = None

    @property
    def process_agent_id(self) -> str | None:
        return self._process_agent_id

    @process_agent_id.setter
    def process_agent_id(self, value: str | None) -> None:
        self._process_agent_id = value

    def get_framework_name(self) -> str:
        return "langchain"

    def get_supported_versions(self) -> list[str]:
        return [">=0.1.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        self._patch = LangChainPatch(
            interceptor,
            process_agent_id=self._process_agent_id,
        )
        self._patch.apply()

    def unregister_hooks(self) -> None:
        if self._patch is not None:
            self._patch.revert()
            self._patch = None

    def get_callback_handler(self) -> Any:
        """Return the active callback handler created during hook registration."""
        return get_active_callback_handler()
