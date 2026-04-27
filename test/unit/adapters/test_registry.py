from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_assembly.adapters import AdapterRegistry, FrameworkAdapter, GovernanceInterceptor


class DummyAdapter(FrameworkAdapter):
    def __init__(self, framework_name: str) -> None:
        self._framework_name = framework_name
        self.register_calls = 0

    def get_framework_name(self) -> str:
        return self._framework_name

    def get_supported_versions(self) -> list[str]:
        return [">=0.1.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        self.register_calls += 1

    def unregister_hooks(self) -> None:
        return None


class EmptyEntryPoints(list[object]):
    def select(self, *, group: str) -> list[object]:
        del group
        return []


class FakeEntryPoint:
    def __init__(self, name: str, loaded: type[FrameworkAdapter]) -> None:
        self.name = name
        self._loaded = loaded

    def load(self) -> type[FrameworkAdapter]:
        return self._loaded


class ThirdPartyAdapter(FrameworkAdapter):
    def get_framework_name(self) -> str:
        return "third_party_framework"

    def get_supported_versions(self) -> list[str]:
        return [">=1.0.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        return None

    def unregister_hooks(self) -> None:
        return None


def test_auto_detect_activates_only_importable_frameworks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AdapterRegistry()
    importable = DummyAdapter("available_framework")
    missing = DummyAdapter("missing_framework")
    registry._registered = {
        importable.get_framework_name(): importable,
        missing.get_framework_name(): missing,
    }

    monkeypatch.setattr(
        "agent_assembly.adapters.registry.metadata.entry_points",
        lambda: EmptyEntryPoints(),
    )

    def fake_import_module(module_name: str) -> object:
        if module_name == "available_framework":
            return SimpleNamespace(__version__="1.2.3")
        raise ImportError

    monkeypatch.setattr("agent_assembly.adapters.base.importlib.import_module", fake_import_module)

    activated = registry.auto_detect()

    assert activated == ["available_framework"]
    assert importable.register_calls == 1
    assert missing.register_calls == 0


def test_entry_point_discovery_loads_third_party_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AdapterRegistry()

    class FakeEntryPoints(list[FakeEntryPoint]):
        def select(self, *, group: str) -> list[FakeEntryPoint]:
            assert group == "agent_assembly.adapters"
            return list(self)

    monkeypatch.setattr(
        "agent_assembly.adapters.registry.metadata.entry_points",
        lambda: FakeEntryPoints([FakeEntryPoint("third-party", ThirdPartyAdapter)]),
    )

    discovered = registry._discover_entry_point_adapters()

    assert discovered == ["third_party_framework"]
    assert "third_party_framework" in registry._registered


def test_auto_detect_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = AdapterRegistry()
    adapter = DummyAdapter("idempotent_framework")
    registry._registered = {adapter.get_framework_name(): adapter}

    monkeypatch.setattr(
        "agent_assembly.adapters.registry.metadata.entry_points",
        lambda: EmptyEntryPoints(),
    )
    monkeypatch.setattr(
        "agent_assembly.adapters.base.importlib.import_module",
        lambda module_name: SimpleNamespace(__version__="9.9.9"),
    )

    first_activation = registry.auto_detect()
    second_activation = registry.auto_detect()

    assert first_activation == ["idempotent_framework"]
    assert second_activation == []
    assert adapter.register_calls == 1
