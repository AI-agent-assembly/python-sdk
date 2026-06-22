"""LlamaIndex framework adapter."""

from __future__ import annotations

from agent_assembly.adapters.base import FrameworkAdapter, GovernanceInterceptor
from agent_assembly.adapters.llamaindex.patch import LlamaIndexPatch


class LlamaIndexAdapter(FrameworkAdapter):
    """Adapter for LlamaIndex framework governance hook installation.

    Wires the SDK-layer pre-execution allow/deny + audit hook onto the
    LlamaIndex tool-execution path (``FunctionTool.call`` / ``acall``). The
    framework package is imported as ``llama_index.core``; the patch targets the
    concrete tool methods the agent loop actually invokes (the base methods are
    abstract).
    """

    def __init__(self, *, process_agent_id: str | None = None) -> None:
        self._process_agent_id = process_agent_id
        self._patch: LlamaIndexPatch | None = None

    @property
    def process_agent_id(self) -> str | None:
        return self._process_agent_id

    @process_agent_id.setter
    def process_agent_id(self, value: str | None) -> None:
        self._process_agent_id = value

    def get_framework_name(self) -> str:
        return "llama_index.core"

    def get_supported_versions(self) -> list[str]:
        return [">=0.10.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        self._patch = LlamaIndexPatch(
            interceptor,
            process_agent_id=self._process_agent_id,
        )
        self._patch.apply()

    def unregister_hooks(self) -> None:
        if self._patch is not None:
            self._patch.revert()
            self._patch = None
