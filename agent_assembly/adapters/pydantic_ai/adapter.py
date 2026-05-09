"""Pydantic AI framework adapter."""

from __future__ import annotations

from agent_assembly.adapters.base import FrameworkAdapter, GovernanceInterceptor
from agent_assembly.adapters.pydantic_ai.patch import PydanticAIPatch


class PydanticAIAdapter(FrameworkAdapter):
    """Adapter for Pydantic AI framework governance hook installation."""

    def __init__(self) -> None:
        self._process_agent_id: str | None = None
        self._patch: PydanticAIPatch | None = None

    @property
    def process_agent_id(self) -> str | None:
        return self._process_agent_id

    @process_agent_id.setter
    def process_agent_id(self, value: str | None) -> None:
        self._process_agent_id = value

    def get_framework_name(self) -> str:
        return "pydantic_ai"

    def get_supported_versions(self) -> list[str]:
        return [">=0.1.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        self._patch = PydanticAIPatch(
            callback_handler=interceptor,
            process_agent_id=self._process_agent_id,
        )
        self._patch.apply()

    def unregister_hooks(self) -> None:
        if self._patch is not None:
            self._patch.revert()
            self._patch = None
