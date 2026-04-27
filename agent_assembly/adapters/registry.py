from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Literal

from agent_assembly.adapters.base import FrameworkAdapter


@dataclass(frozen=True, slots=True)
class AdapterInfo:
    name: str
    version: str
    status: Literal["active", "error"]
    hooks_registered: int


class _BuiltinPlaceholderAdapter(FrameworkAdapter):
    def __init__(self, framework_name: str) -> None:
        self._framework_name = framework_name

    def get_framework_name(self) -> str:
        return self._framework_name

    def get_supported_versions(self) -> list[str]:
        return [">=0.0.0"]

    def register_hooks(self, interceptor: object) -> None:
        return None

    def unregister_hooks(self) -> None:
        return None


class AdapterRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._registered: dict[str, FrameworkAdapter] = {}
        self._active: dict[str, FrameworkAdapter] = {}
        for framework_name in ("langchain", "langgraph", "crewai", "pydantic_ai"):
            self._registered[framework_name] = _BuiltinPlaceholderAdapter(framework_name)

    def register(self, adapter: FrameworkAdapter) -> None:
        adapter_name = adapter.get_framework_name()
        with self._lock:
            self._registered[adapter_name] = adapter
            if adapter_name in self._active and self._active[adapter_name] is not adapter:
                self._active.pop(adapter_name, None)
