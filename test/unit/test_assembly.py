from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any

import pytest

from agent_assembly import init_assembly
from agent_assembly.adapters.base import FrameworkAdapter, GovernanceInterceptor
from agent_assembly.core import assembly as core_assembly
from agent_assembly.exceptions import AssemblyError, ConfigurationError


class _FakeAdapter(FrameworkAdapter):
    """Minimal adapter for testing init_assembly plumbing."""

    def __init__(self, name: str = "fake") -> None:
        self._name = name
        self._registered = False

    def get_framework_name(self) -> str:
        return self._name

    def get_supported_versions(self) -> list[str]:
        return [">=0.0.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        self._registered = True

    def unregister_hooks(self) -> None:
        self._registered = False


@pytest.fixture(autouse=True)
def cleanup_active_context() -> None:
    active_context = core_assembly._ACTIVE_CONTEXT
    if active_context is not None and not active_context.is_shutdown:
        active_context.shutdown()
    core_assembly._ACTIVE_CONTEXT = None


def test_init_assembly_with_valid_config_returns_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **kwargs: [])
    monkeypatch.setattr(
        core_assembly,
        "_start_network_layer",
        lambda **kwargs: ("sdk-only", core_assembly._noop_shutdown),
    )

    context = init_assembly(
        gateway_url="http://localhost:8080",
        api_key="test-api-key",
        agent_id="test-agent-001",
    )

    try:
        assert context.client.agent_id == "test-agent-001"
        assert context.client.gateway_url == "http://localhost:8080"
        assert context.client.api_key == "test-api-key"
        assert context.network_mode == "sdk-only"
        assert context.adapters == []
    finally:
        context.shutdown()


def test_init_assembly_with_invalid_config() -> None:
    with pytest.raises(ConfigurationError):
        init_assembly(
            gateway_url="http://localhost:8080",
            api_key="test-api-key",
            mode="invalid-mode",  # type: ignore[arg-type]
        )


def test_init_assembly_zero_arg_resolves_local_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AAASM-1846 AC: init_assembly() with no args connects to local default."""
    from agent_assembly.core import gateway_resolver

    monkeypatch.setattr(gateway_resolver, "_probe_healthz", lambda _url: True)
    monkeypatch.delenv(gateway_resolver.ENV_GATEWAY_URL, raising=False)
    monkeypatch.delenv(gateway_resolver.ENV_API_KEY, raising=False)
    monkeypatch.setattr(gateway_resolver, "_load_config_file", lambda: {})
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **kwargs: [])
    monkeypatch.setattr(
        core_assembly,
        "_start_network_layer",
        lambda **kwargs: ("sdk-only", core_assembly._noop_shutdown),
    )

    context = init_assembly()
    try:
        assert context.client.gateway_url == gateway_resolver.DEFAULT_GATEWAY_URL
        assert context.client.api_key == ""
    finally:
        context.shutdown()


def test_init_assembly_explicit_args_bypass_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AAASM-1846 regression: explicit gateway_url / api_key still bind verbatim."""
    from agent_assembly.core import gateway_resolver

    def _fail_probe(_url: str) -> bool:
        raise AssertionError("resolver should not probe when explicit args provided")

    def _fail_auto_start(_url: str = "") -> None:
        raise AssertionError("resolver should not auto-start when explicit args provided")

    monkeypatch.setattr(gateway_resolver, "_probe_healthz", _fail_probe)
    monkeypatch.setattr(gateway_resolver, "_auto_start_gateway", _fail_auto_start)
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **kwargs: [])
    monkeypatch.setattr(
        core_assembly,
        "_start_network_layer",
        lambda **kwargs: ("sdk-only", core_assembly._noop_shutdown),
    )

    context = init_assembly(
        gateway_url="http://explicit.gw:9999",
        api_key="explicit-key",
        agent_id="agent-x",
    )
    try:
        assert context.client.gateway_url == "http://explicit.gw:9999"
        assert context.client.api_key == "explicit-key"
        assert context.client.agent_id == "agent-x"
    finally:
        context.shutdown()


def test_mode_sdk_only_skips_network_layer() -> None:
    network_mode, shutdown = core_assembly._start_network_layer(client=object(), mode="sdk-only")
    assert network_mode == "sdk-only"
    assert callable(shutdown)


def test_mode_auto_uses_proxy_when_ebpf_is_not_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core_assembly, "_platform_supports_ebpf", lambda: False)
    monkeypatch.setattr(core_assembly, "_start_mitm_proxy", lambda client: lambda: None)

    network_mode, shutdown = core_assembly._start_network_layer(client=object(), mode="auto")

    assert network_mode == "proxy"
    assert callable(shutdown)


def test_mode_auto_uses_ebpf_when_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core_assembly, "_platform_supports_ebpf", lambda: True)
    monkeypatch.setattr(core_assembly, "_start_ebpf_probes", lambda client: lambda: None)

    network_mode, shutdown = core_assembly._start_network_layer(client=object(), mode="auto")
    assert network_mode == "ebpf"
    assert callable(shutdown)


def test_mode_proxy_forces_proxy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core_assembly, "_start_mitm_proxy", lambda client: lambda: None)
    network_mode, shutdown = core_assembly._start_network_layer(client=object(), mode="proxy")
    assert network_mode == "proxy"
    assert callable(shutdown)


def test_mode_ebpf_raises_on_unsupported_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core_assembly, "_platform_supports_ebpf", lambda: False)

    with pytest.raises(ConfigurationError):
        core_assembly._start_network_layer(client=object(), mode="ebpf")


def test_context_manager_shutdown_calls_adapter_unregister_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class _TrackingAdapter(_FakeAdapter):
        def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
            events.append(f"register:{self._name}")

        def unregister_hooks(self) -> None:
            events.append(f"unregister:{self._name}")

    monkeypatch.setattr(
        core_assembly,
        "_register_adapters",
        lambda **kwargs: [_TrackingAdapter("a"), _TrackingAdapter("b")],
    )
    monkeypatch.setattr(
        core_assembly,
        "_start_network_layer",
        lambda **kwargs: ("sdk-only", core_assembly._noop_shutdown),
    )

    with init_assembly(
        gateway_url="http://localhost:8080",
        api_key="test-api-key",
    ) as context:
        assert context.is_shutdown is False

    assert events == ["unregister:b", "unregister:a"]
    assert context.is_shutdown is True


def test_init_assembly_rejects_conflicting_reinit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **kwargs: [])
    monkeypatch.setattr(
        core_assembly,
        "_start_network_layer",
        lambda **kwargs: ("sdk-only", core_assembly._noop_shutdown),
    )

    context = init_assembly(
        gateway_url="http://localhost:8080",
        api_key="test-api-key",
        agent_id="agent-a",
    )
    try:
        with pytest.raises(ConfigurationError, match="different agent_id"):
            init_assembly(
                gateway_url="http://localhost:8080",
                api_key="test-api-key",
                agent_id="agent-b",
            )
    finally:
        context.shutdown()


def test_init_assembly_rejects_conflicting_gateway_and_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **kwargs: [])
    monkeypatch.setattr(
        core_assembly,
        "_start_network_layer",
        lambda **kwargs: ("sdk-only", core_assembly._noop_shutdown),
    )

    context = init_assembly(
        gateway_url="http://localhost:8080",
        api_key="test-api-key",
        agent_id="agent-a",
    )
    try:
        with pytest.raises(ConfigurationError, match="different gateway_url"):
            init_assembly(
                gateway_url="http://localhost:9090",
                api_key="test-api-key",
                agent_id="agent-a",
            )
        with pytest.raises(ConfigurationError, match="different api_key"):
            init_assembly(
                gateway_url="http://localhost:8080",
                api_key="test-api-key-2",
                agent_id="agent-a",
            )
    finally:
        context.shutdown()


def test_context_shutdown_aggregates_errors() -> None:
    class _FailingAdapter(_FakeAdapter):
        def unregister_hooks(self) -> None:
            raise RuntimeError("adapter failure")

    class _FailingClient:
        gateway_url = "http://localhost:8080"
        api_key = "test-api-key"
        agent_id = "test-agent"

        def close(self) -> None:
            raise RuntimeError("close failure")

    context = core_assembly.AssemblyContext(
        client=_FailingClient(),  # type: ignore[arg-type]
        adapters=[_FailingAdapter("fail")],
        network_mode="sdk-only",
        _network_shutdown=lambda: (_ for _ in ()).throw(RuntimeError("network failure")),
    )

    with pytest.raises(AssemblyError, match="network shutdown failed"):
        context.shutdown()


def test_unregister_adapters_ignores_unregister_failures() -> None:
    class _AdapterOk(_FakeAdapter):
        def unregister_hooks(self) -> None:
            return None

    class _AdapterFails(_FakeAdapter):
        def unregister_hooks(self) -> None:
            raise RuntimeError("boom")

    core_assembly._unregister_adapters([_AdapterOk("ok1"), _AdapterFails("fail"), _AdapterOk("ok2")])  # no raise


def test_init_assembly_is_thread_safe_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()
    register_call_count = 0

    def fake_register_adapters(**kwargs: Any) -> list[Any]:
        nonlocal register_call_count
        register_call_count += 1
        started.set()
        release.wait(timeout=2)
        return []

    monkeypatch.setattr(core_assembly, "_register_adapters", fake_register_adapters)
    monkeypatch.setattr(
        core_assembly,
        "_start_network_layer",
        lambda **kwargs: ("sdk-only", core_assembly._noop_shutdown),
    )

    def initialize() -> core_assembly.AssemblyContext:
        return init_assembly(gateway_url="http://localhost:8080", api_key="test-api-key")

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_a = executor.submit(initialize)
        started.wait(timeout=2)
        future_b = executor.submit(initialize)
        release.set()

        context_a = future_a.result()
        context_b = future_b.result()

    try:
        assert context_a is context_b
        assert register_call_count == 1
    finally:
        context_a.shutdown()


@pytest.mark.parametrize(
    ("parent_agent_id", "team_id", "delegation_reason", "spawned_by_tool"),
    [
        ("parent-agent", "team-1", "delegated sub-task", "search_tool"),
        ("parent-agent", None, None, None),
        (None, "team-1", None, None),
        (None, None, "delegated sub-task", None),
        (None, None, None, "search_tool"),
    ],
)
def test_init_assembly_topology_params_forwarded_to_client(
    monkeypatch: pytest.MonkeyPatch,
    parent_agent_id: str | None,
    team_id: str | None,
    delegation_reason: str | None,
    spawned_by_tool: str | None,
) -> None:
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **kwargs: [])
    monkeypatch.setattr(
        core_assembly,
        "_start_network_layer",
        lambda **kwargs: ("sdk-only", core_assembly._noop_shutdown),
    )

    context = init_assembly(
        gateway_url="http://localhost:8080",
        api_key="test-api-key",
        agent_id="child-agent",
        parent_agent_id=parent_agent_id,
        team_id=team_id,
        delegation_reason=delegation_reason,
        spawned_by_tool=spawned_by_tool,
    )

    try:
        assert context.client.parent_agent_id == parent_agent_id
        assert context.client.team_id == team_id
        assert context.client.delegation_reason == delegation_reason
        assert context.client.spawned_by_tool == spawned_by_tool
    finally:
        context.shutdown()


def test_init_assembly_without_topology_params_is_backward_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **kwargs: [])
    monkeypatch.setattr(
        core_assembly,
        "_start_network_layer",
        lambda **kwargs: ("sdk-only", core_assembly._noop_shutdown),
    )

    context = init_assembly(
        gateway_url="http://localhost:8080",
        api_key="test-api-key",
    )

    try:
        assert context.client.parent_agent_id is None
        assert context.client.team_id is None
        assert context.client.delegation_reason is None
        assert context.client.spawned_by_tool is None
    finally:
        context.shutdown()


def test_init_assembly_delegation_reason_too_long_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **kwargs: [])
    monkeypatch.setattr(
        core_assembly,
        "_start_network_layer",
        lambda **kwargs: ("sdk-only", core_assembly._noop_shutdown),
    )

    with pytest.raises(ValueError, match="delegation_reason must be <= 256 characters"):
        init_assembly(
            gateway_url="http://localhost:8080",
            api_key="test-api-key",
            delegation_reason="x" * 257,
        )
