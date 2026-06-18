"""Edge-case and error-path tests for `AdapterRegistry`.

Complements `test_registry.py` (happy-path discovery/activation) by covering the
branches that only fire on malformed entry points, replacement of an active
adapter, error-state reporting via `list_active`, and an adapter that raises
during activation.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters import (
    AdapterRegistry,
    FrameworkAdapter,
    GovernanceInterceptor,
)


class _EmptyEntryPoints(list[object]):
    def select(self, *, group: str) -> list[object]:
        del group
        return []


class _DummyAdapter(FrameworkAdapter):
    def __init__(self, framework_name: str, *, version: str | None = "1.0.0") -> None:
        self._framework_name = framework_name
        self._version = version
        self.unregister_calls = 0

    def get_framework_name(self) -> str:
        return self._framework_name

    def get_supported_versions(self) -> list[str]:
        return [">=0.1.0"]

    def get_active_version(self) -> str | None:
        return self._version

    def register_hooks(self, _interceptor: GovernanceInterceptor) -> None:
        return None

    def unregister_hooks(self) -> None:
        self.unregister_calls += 1


def _no_entry_points(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agent_assembly.adapters.registry.metadata.entry_points",
        lambda: _EmptyEntryPoints(),
    )


def test_register_replacing_active_adapter_drops_stale_active_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AdapterRegistry()
    first = _DummyAdapter("dup_framework")
    registry._registered = {"dup_framework": first}
    _no_entry_points(monkeypatch)
    monkeypatch.setattr(
        "agent_assembly.adapters.base.importlib.import_module",
        lambda _module_name: SimpleNamespace(__version__="1.0.0"),
    )

    registry.auto_detect()
    assert registry._active["dup_framework"] is first

    # Registering a *different* instance under the same name evicts the active one.
    replacement = _DummyAdapter("dup_framework")
    registry.register(replacement)

    assert "dup_framework" not in registry._active
    assert registry._registered["dup_framework"] is replacement


def test_unregister_calls_unregister_hooks_on_active_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AdapterRegistry()
    adapter = _DummyAdapter("teardown_framework")
    registry._registered = {"teardown_framework": adapter}
    _no_entry_points(monkeypatch)
    monkeypatch.setattr(
        "agent_assembly.adapters.base.importlib.import_module",
        lambda _module_name: SimpleNamespace(__version__="1.0.0"),
    )

    registry.auto_detect()
    registry.unregister("teardown_framework")

    assert adapter.unregister_calls == 1


def test_list_active_coerces_non_int_hook_count_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AdapterRegistry()
    adapter = _DummyAdapter("hooky_framework")
    # A non-int hook count must be coerced to 0 in the AdapterInfo.
    adapter._hooks_registered_count = "not-an-int"  # type: ignore[attr-defined]
    registry._active = {"hooky_framework": adapter}

    infos = registry.list_active()

    assert len(infos) == 1
    assert infos[0].hooks_registered == 0
    assert infos[0].status == "active"


def test_list_active_includes_error_only_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = AdapterRegistry()
    registry._active = {}
    registry._errors = {"broken_framework": "load failed"}

    infos = registry.list_active()

    assert len(infos) == 1
    assert infos[0].name == "broken_framework"
    assert infos[0].status == "error"
    assert infos[0].hooks_registered == 0


def test_get_available_adapters_by_priority_orders_and_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AdapterRegistry()
    # langchain has priority 0 (first), mcp has 99 (last); an unknown framework
    # falls into the default priority slot between them.
    langchain = _DummyAdapter("langchain")
    mcp = _DummyAdapter("mcp")
    unavailable = _DummyAdapter("offline_framework")
    registry._registered = {
        "mcp": mcp,
        "offline_framework": unavailable,
        "langchain": langchain,
    }
    _no_entry_points(monkeypatch)

    def fake_import_module(module_name: str) -> Any:
        if module_name in ("langchain", "mcp"):
            return SimpleNamespace(__version__="1.0.0")
        raise ImportError

    monkeypatch.setattr("agent_assembly.adapters.base.importlib.import_module", fake_import_module)

    available = registry.get_available_adapters_by_priority()

    names = [a.get_framework_name() for a in available]
    assert names == ["langchain", "mcp"]
    assert "offline_framework" not in names


class _FakeEntryPoint:
    def __init__(self, name: str, loaded: object) -> None:
        self.name = name
        self._loaded = loaded

    def load(self) -> object:
        return self._loaded


def _patch_entry_points(monkeypatch: pytest.MonkeyPatch, eps: list[_FakeEntryPoint]) -> None:
    class _FakeEntryPoints(list[_FakeEntryPoint]):
        def select(self, *, group: str) -> list[_FakeEntryPoint]:
            assert group == "agent_assembly.adapters"
            return list(self)

    monkeypatch.setattr(
        "agent_assembly.adapters.registry.metadata.entry_points",
        lambda: _FakeEntryPoints(eps),
    )


def test_discover_records_error_when_entry_point_is_not_a_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AdapterRegistry()
    _patch_entry_points(monkeypatch, [_FakeEntryPoint("not-a-class", object())])

    discovered = registry._discover_entry_point_adapters()

    assert discovered == []
    assert registry._errors["not-a-class"] == "Entry point did not load a class."


def test_discover_records_error_when_class_is_not_a_framework_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NotAnAdapter: ...

    registry = AdapterRegistry()
    _patch_entry_points(monkeypatch, [_FakeEntryPoint("wrong-class", NotAnAdapter)])

    discovered = registry._discover_entry_point_adapters()

    assert discovered == []
    assert registry._errors["wrong-class"] == "Entry point class is not a FrameworkAdapter."


class _RaisingAdapter(FrameworkAdapter):
    def get_framework_name(self) -> str:
        return "raising_framework"

    def get_supported_versions(self) -> list[str]:
        return [">=0.1.0"]

    def register(self, _interceptor: GovernanceInterceptor) -> None:
        raise RuntimeError("hook wiring failed")

    def register_hooks(self, _interceptor: GovernanceInterceptor) -> None:
        return None

    def unregister_hooks(self) -> None:
        return None


def test_auto_detect_records_error_when_adapter_register_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AdapterRegistry()
    adapter = _RaisingAdapter()
    registry._registered = {"raising_framework": adapter}
    _no_entry_points(monkeypatch)

    def fake_import_module(module_name: str) -> Any:
        if module_name == "raising_framework":
            return SimpleNamespace(__version__="1.0.0")
        raise ImportError

    monkeypatch.setattr("agent_assembly.adapters.base.importlib.import_module", fake_import_module)

    activated = registry.auto_detect()

    assert activated == []
    assert registry._errors["raising_framework"] == "hook wiring failed"
    assert "raising_framework" not in registry._active
