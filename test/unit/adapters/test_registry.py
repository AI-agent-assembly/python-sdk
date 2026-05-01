from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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


class CountingEntryPointAdapter(FrameworkAdapter):
    register_calls = 0

    def get_framework_name(self) -> str:
        return "entrypoint_counting_framework"

    def get_supported_versions(self) -> list[str]:
        return [">=1.0.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        CountingEntryPointAdapter.register_calls += 1

    def unregister_hooks(self) -> None:
        return None


class InterceptorCallingAdapter(FrameworkAdapter):
    def __init__(self) -> None:
        self.hook_registered = False

    def get_framework_name(self) -> str:
        return "interceptor_calling_framework"

    def get_supported_versions(self) -> list[str]:
        return [">=1.0.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        interceptor.record_event("adapter-registered")
        self.hook_registered = True

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


def test_list_active_reflects_real_time_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AdapterRegistry()
    adapter = DummyAdapter("stateful_framework")
    registry._registered = {adapter.get_framework_name(): adapter}

    monkeypatch.setattr(
        "agent_assembly.adapters.registry.metadata.entry_points",
        lambda: EmptyEntryPoints(),
    )
    monkeypatch.setattr(
        "agent_assembly.adapters.base.importlib.import_module",
        lambda module_name: SimpleNamespace(__version__="2.0.0"),
    )

    registry.auto_detect()
    active_after_detect = registry.list_active()

    assert len(active_after_detect) == 1
    assert active_after_detect[0].name == "stateful_framework"
    assert active_after_detect[0].status == "active"

    registry.unregister("stateful_framework")

    assert registry.list_active() == []


def test_register_unregister_is_thread_safe() -> None:
    registry = AdapterRegistry()

    def mutate_registry(thread_id: int) -> None:
        for round_id in range(40):
            adapter = DummyAdapter(f"concurrent_{thread_id}_{round_id}")
            registry.register(adapter)
            registry.unregister(adapter.get_framework_name())

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(mutate_registry, thread_id) for thread_id in range(8)]
        for future in futures:
            future.result()

    with registry._lock:
        assert isinstance(registry._registered, dict)
        assert isinstance(registry._active, dict)


def test_auto_detect_is_idempotent_for_entry_point_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AdapterRegistry()
    CountingEntryPointAdapter.register_calls = 0

    class FakeEntryPoints(list[FakeEntryPoint]):
        def select(self, *, group: str) -> list[FakeEntryPoint]:
            assert group == "agent_assembly.adapters"
            return list(self)

    monkeypatch.setattr(
        "agent_assembly.adapters.registry.metadata.entry_points",
        lambda: FakeEntryPoints([FakeEntryPoint("counting-entrypoint", CountingEntryPointAdapter)]),
    )

    def fake_import_module(module_name: str) -> object:
        if module_name == "entrypoint_counting_framework":
            return SimpleNamespace(__version__="3.0.0")
        raise ImportError

    monkeypatch.setattr("agent_assembly.adapters.base.importlib.import_module", fake_import_module)

    first = registry.auto_detect()
    second = registry.auto_detect()

    assert first == ["entrypoint_counting_framework"]
    assert second == []
    assert CountingEntryPointAdapter.register_calls == 1


def test_auto_detect_uses_resilient_noop_interceptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AdapterRegistry()
    adapter = InterceptorCallingAdapter()
    registry._registered = {adapter.get_framework_name(): adapter}

    monkeypatch.setattr(
        "agent_assembly.adapters.registry.metadata.entry_points",
        lambda: EmptyEntryPoints(),
    )

    def fake_import_module(module_name: str) -> object:
        if module_name == "interceptor_calling_framework":
            return SimpleNamespace(__version__="1.0.0")
        raise ImportError

    monkeypatch.setattr("agent_assembly.adapters.base.importlib.import_module", fake_import_module)

    activated = registry.auto_detect()

    assert activated == ["interceptor_calling_framework"]
    assert adapter.hook_registered is True


def test_builtin_registry_keys_match_adapter_framework_name() -> None:
    registry = AdapterRegistry()

    assert "pydantic_ai" in registry._registered
    assert registry._registered["pydantic_ai"].get_framework_name() == "pydantic_ai"
