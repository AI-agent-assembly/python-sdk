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
