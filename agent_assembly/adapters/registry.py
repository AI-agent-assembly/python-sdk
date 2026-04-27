from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
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

    def unregister(self, name: str) -> None:
        with self._lock:
            active_adapter = self._active.pop(name, None)
            self._registered.pop(name, None)

        if active_adapter is not None:
            active_adapter.unregister_hooks()

    def list_active(self) -> list[AdapterInfo]:
        with self._lock:
            active_items = list(self._active.items())

        result: list[AdapterInfo] = []
        for name, adapter in active_items:
            hooks_registered = getattr(adapter, "_hooks_registered_count", 0)
            if not isinstance(hooks_registered, int):
                hooks_registered = 0

            result.append(
                AdapterInfo(
                    name=name,
                    version=adapter.get_active_version() or "",
                    status="active",
                    hooks_registered=hooks_registered,
                )
            )

        return sorted(result, key=lambda info: info.name)

    def _discover_entry_point_adapters(self) -> list[str]:
        discovered: list[str] = []
        entry_points = metadata.entry_points()
        adapter_entry_points = entry_points.select(group="agent_assembly.adapters")

        for entry_point in adapter_entry_points:
            loaded = entry_point.load()
            if not isinstance(loaded, type):
                continue

            if not issubclass(loaded, FrameworkAdapter):
                continue

            adapter = loaded()
            self.register(adapter)
            discovered.append(adapter.get_framework_name())

        return discovered
