from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from threading import Lock
from typing import Callable, Literal

from agent_assembly.adapters.base import FrameworkAdapter
from agent_assembly.adapters.crewai.adapter import CrewAIAdapter
from agent_assembly.adapters.google_adk.adapter import GoogleADKAdapter
from agent_assembly.adapters.langchain.adapter import LangChainAdapter
from agent_assembly.adapters.langgraph.adapter import LangGraphAdapter
from agent_assembly.adapters.mcp.adapter import MCPAdapter
from agent_assembly.adapters.openai_agents.adapter import OpenAIAgentsAdapter
from agent_assembly.adapters.pydantic_ai.adapter import PydanticAIAdapter

# LangChain must be first: its callback handler threads through to all
# subsequent adapters.  MCP must be last: it acts as a fallback for
# remaining tool dispatch paths.
_ADAPTER_PRIORITY: dict[str, int] = {
    "langchain": 0,
    "langgraph": 1,
    "crewai": 2,
    "pydantic_ai": 3,
    "openai": 4,
    "google_adk": 5,
    "mcp": 99,
}

_DEFAULT_PRIORITY = 50


@dataclass(frozen=True, slots=True)
class AdapterInfo:
    name: str
    version: str
    status: Literal["active", "error"]
    hooks_registered: int


def _noop_interceptor_method(*args: object, **kwargs: object) -> None:
    del args, kwargs
    return None


class _NoopGovernanceInterceptor:
    def __getattr__(self, name: str) -> Callable[..., None]:
        del name
        return _noop_interceptor_method


_NOOP_GOVERNANCE_INTERCEPTOR = _NoopGovernanceInterceptor()


class AdapterRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._registered: dict[str, FrameworkAdapter] = {}
        self._active: dict[str, FrameworkAdapter] = {}
        self._errors: dict[str, str] = {}
        self._discovered_entry_points: set[str] = set()
        builtin_adapters: list[FrameworkAdapter] = [
            LangChainAdapter(),
            LangGraphAdapter(),
            CrewAIAdapter(),
            PydanticAIAdapter(),
            OpenAIAgentsAdapter(),
            GoogleADKAdapter(),
            MCPAdapter(),
        ]
        for adapter in builtin_adapters:
            self._registered[adapter.get_framework_name()] = adapter

    def register(self, adapter: FrameworkAdapter) -> None:
        adapter_name = adapter.get_framework_name()
        with self._lock:
            self._registered[adapter_name] = adapter
            self._errors.pop(adapter_name, None)
            if adapter_name in self._active and self._active[adapter_name] is not adapter:
                self._active.pop(adapter_name, None)

    def unregister(self, name: str) -> None:
        with self._lock:
            active_adapter = self._active.pop(name, None)
            self._registered.pop(name, None)
            self._errors.pop(name, None)

        if active_adapter is not None:
            active_adapter.unregister_hooks()

    def list_active(self) -> list[AdapterInfo]:
        with self._lock:
            active_items = list(self._active.items())
            error_names = set(self._errors.keys())

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

        active_names = {name for name, _ in active_items}
        for name in sorted(error_names - active_names):
            result.append(
                AdapterInfo(
                    name=name,
                    version="",
                    status="error",
                    hooks_registered=0,
                )
            )

        return sorted(result, key=lambda info: info.name)

    def get_available_adapters_by_priority(self) -> list[FrameworkAdapter]:
        """Return available adapters sorted by registration priority.

        This method discovers entry-point adapters, checks availability,
        and returns adapters in the order they should be registered by
        ``init_assembly()``.  It does **not** call ``register_hooks()``
        — that is the caller's responsibility.
        """
        self._discover_entry_point_adapters()

        with self._lock:
            registered_items = list(self._registered.items())

        available: list[FrameworkAdapter] = []
        for _name, adapter in registered_items:
            if adapter.is_available():
                available.append(adapter)

        available.sort(key=lambda a: _ADAPTER_PRIORITY.get(a.get_framework_name(), _DEFAULT_PRIORITY))
        return available

    def _discover_entry_point_adapters(self) -> list[str]:
        discovered: list[str] = []
        entry_points = metadata.entry_points()
        adapter_entry_points = entry_points.select(group="agent_assembly.adapters")

        for entry_point in adapter_entry_points:
            with self._lock:
                if entry_point.name in self._discovered_entry_points:
                    continue

            try:
                loaded = entry_point.load()
            except Exception as error:  # pragma: no cover - guarded by tests via monkeypatch
                with self._lock:
                    self._errors[entry_point.name] = str(error)
                continue

            if not isinstance(loaded, type):
                with self._lock:
                    self._errors[entry_point.name] = "Entry point did not load a class."
                continue

            if not issubclass(loaded, FrameworkAdapter):
                with self._lock:
                    self._errors[entry_point.name] = "Entry point class is not a FrameworkAdapter."
                continue

            try:
                adapter = loaded()
            except Exception as error:  # pragma: no cover - guarded by tests via monkeypatch
                with self._lock:
                    self._errors[entry_point.name] = str(error)
                continue

            self.register(adapter)
            with self._lock:
                self._discovered_entry_points.add(entry_point.name)
            discovered.append(adapter.get_framework_name())

        return discovered

    def auto_detect(self) -> list[str]:
        self._discover_entry_point_adapters()

        with self._lock:
            registered_items = list(self._registered.items())

        activated: list[str] = []
        for name, adapter in registered_items:
            if not adapter.is_available():
                continue

            with self._lock:
                if self._active.get(name) is adapter:
                    continue

            try:
                adapter.register(_NOOP_GOVERNANCE_INTERCEPTOR)
            except Exception as error:
                with self._lock:
                    self._errors[name] = str(error)
                continue

            with self._lock:
                self._active[name] = adapter
                self._errors.pop(name, None)
            activated.append(name)

        return activated
