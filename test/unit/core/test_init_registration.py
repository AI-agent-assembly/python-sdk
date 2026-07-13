"""Tests for the native register / pre-execution check wiring (AAASM-3402).

Closes the unwired-enforcement gap: ``init_assembly`` must register the agent
over the native gRPC path on startup, and the interceptor it hands the adapters
must block a tool call when the native ``query_policy`` returns ``deny``.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_assembly import init_assembly
from agent_assembly.adapters.base import FrameworkAdapter, GovernanceInterceptor
from agent_assembly.core import assembly as core_assembly
from agent_assembly.core.runtime_interceptor import build_governance_interceptor
from agent_assembly.core.spawn import SpawnContext, spawn_context_scope
from agent_assembly.exceptions import ConfigurationError

from ._fake_core import (
    FakeRuntimeClient,
    LegacyRuntimeClient,
    install_fake_core,
    install_fake_core_with_connect,
)

_GW_URL = "http://gateway.test"
_API_KEY = "test-key"
# The gRPC register endpoint derived from _GW_URL's host with the gateway gRPC
# port (:50051) substituted for the REST port — see resolve_gateway_grpc_endpoint
# (AAASM-4547). register_agent forwards this as the 4th positional argument.
_GRPC_ENDPOINT = "http://gateway.test:50051"


class _CapturingAdapter(FrameworkAdapter):
    """Adapter that records the interceptor it is handed at register_hooks."""

    def __init__(self) -> None:
        self.interceptor: GovernanceInterceptor | None = None

    def get_framework_name(self) -> str:
        return "capturing"

    def get_supported_versions(self) -> list[str]:
        return [">=0.0.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        self.interceptor = interceptor

    def unregister_hooks(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _cleanup_active_context() -> None:
    active = core_assembly._ACTIVE_CONTEXT
    if active is not None and not active.is_shutdown:
        active.shutdown()
    core_assembly._ACTIVE_CONTEXT = None


def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        core_assembly,
        "_start_network_layer",
        lambda **_kwargs: ("sdk-only", core_assembly._noop_shutdown),
    )


def test_init_assembly_registers_agent_on_init(monkeypatch: pytest.MonkeyPatch) -> None:
    """init_assembly calls the native register so the gateway knows the agent."""
    runtime_client = FakeRuntimeClient(decision="allow")
    install_fake_core(monkeypatch, runtime_client)
    _no_network(monkeypatch)
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **_kwargs: [])

    context = init_assembly(gateway_url=_GW_URL, api_key=_API_KEY, agent_id="agent-7", mode="sdk-only")
    try:
        assert runtime_client.register_calls == [("agent-7", "agent-7", "python", _GRPC_ENDPOINT, None, None)]
    finally:
        context.shutdown()


def test_init_assembly_forwards_team_and_parent_on_register(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """init_assembly forwards team_id/parent_agent_id to the native register (AAASM-3415)."""
    runtime_client = FakeRuntimeClient(decision="allow")
    install_fake_core(monkeypatch, runtime_client)
    _no_network(monkeypatch)
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **_kwargs: [])

    context = init_assembly(
        gateway_url=_GW_URL,
        api_key=_API_KEY,
        agent_id="child-1",
        mode="sdk-only",
        team_id="team-payments",
        parent_agent_id="parent-42",
    )
    try:
        assert runtime_client.register_calls == [
            ("child-1", "child-1", "python", _GRPC_ENDPOINT, "team-payments", "parent-42")
        ]
    finally:
        context.shutdown()


def test_init_assembly_forwards_only_team_when_parent_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only ``team_id`` set → team forwarded, parent stays ``None`` (AAASM-3415)."""
    runtime_client = FakeRuntimeClient(decision="allow")
    install_fake_core(monkeypatch, runtime_client)
    _no_network(monkeypatch)
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **_kwargs: [])

    context = init_assembly(
        gateway_url=_GW_URL,
        api_key=_API_KEY,
        agent_id="team-only",
        mode="sdk-only",
        team_id="team-billing",
    )
    try:
        assert runtime_client.register_calls == [
            ("team-only", "team-only", "python", _GRPC_ENDPOINT, "team-billing", None)
        ]
    finally:
        context.shutdown()


def test_init_assembly_forwards_only_parent_when_team_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only ``parent_agent_id`` set → parent forwarded, team stays ``None`` (AAASM-3415)."""
    runtime_client = FakeRuntimeClient(decision="allow")
    install_fake_core(monkeypatch, runtime_client)
    _no_network(monkeypatch)
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **_kwargs: [])

    context = init_assembly(
        gateway_url=_GW_URL,
        api_key=_API_KEY,
        agent_id="parent-only",
        mode="sdk-only",
        parent_agent_id="orchestrator-1",
    )
    try:
        assert runtime_client.register_calls == [
            ("parent-only", "parent-only", "python", _GRPC_ENDPOINT, None, "orchestrator-1")
        ]
    finally:
        context.shutdown()


def test_init_assembly_no_lineage_when_neither_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither lineage field set → both forwarded as ``None``, no crash (AAASM-3415)."""
    runtime_client = FakeRuntimeClient(decision="allow")
    install_fake_core(monkeypatch, runtime_client)
    _no_network(monkeypatch)
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **_kwargs: [])

    context = init_assembly(
        gateway_url=_GW_URL,
        api_key=_API_KEY,
        agent_id="solo",
        mode="sdk-only",
    )
    try:
        assert runtime_client.register_calls == [("solo", "solo", "python", _GRPC_ENDPOINT, None, None)]
    finally:
        context.shutdown()


def test_init_assembly_forwards_ambient_spawn_parent_on_register(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ambient spawn lineage fills ``parent_agent_id`` when config omits it (AAASM-3415).

    A spawned child that does not pass ``parent_agent_id`` explicitly inherits it
    from the ambient ``_SPAWN_CTX`` set at the spawn point, and that implicit
    parent is forwarded to the native register.
    """
    runtime_client = FakeRuntimeClient(decision="allow")
    install_fake_core(monkeypatch, runtime_client)
    _no_network(monkeypatch)
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **_kwargs: [])

    ctx = SpawnContext(parent_agent_id="ambient-parent", depth=1, spawned_by_tool="delegate")
    with spawn_context_scope(ctx):
        context = init_assembly(
            gateway_url=_GW_URL,
            api_key=_API_KEY,
            agent_id="spawned-child",
            mode="sdk-only",
        )
    try:
        assert runtime_client.register_calls == [
            ("spawned-child", "spawned-child", "python", _GRPC_ENDPOINT, None, "ambient-parent")
        ]
    finally:
        context.shutdown()


def test_explicit_parent_overrides_ambient_spawn_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit ``parent_agent_id`` wins over the ambient spawn parent (AAASM-3415)."""
    runtime_client = FakeRuntimeClient(decision="allow")
    install_fake_core(monkeypatch, runtime_client)
    _no_network(monkeypatch)
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **_kwargs: [])

    ctx = SpawnContext(parent_agent_id="ambient-parent", depth=2, spawned_by_tool="delegate")
    with spawn_context_scope(ctx):
        context = init_assembly(
            gateway_url=_GW_URL,
            api_key=_API_KEY,
            agent_id="override-child",
            mode="sdk-only",
            parent_agent_id="explicit-parent",
        )
    try:
        assert runtime_client.register_calls == [
            ("override-child", "override-child", "python", _GRPC_ENDPOINT, None, "explicit-parent")
        ]
    finally:
        context.shutdown()


def test_register_falls_back_on_older_native_build_without_lineage_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An older native ``register`` (no lineage kwargs) is retried with the legacy
    positional signature rather than crashing (AAASM-3415)."""
    legacy_client = LegacyRuntimeClient()
    install_fake_core(monkeypatch, legacy_client)
    _no_network(monkeypatch)
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **_kwargs: [])

    context = init_assembly(
        gateway_url=_GW_URL,
        api_key=_API_KEY,
        agent_id="legacy-agent",
        mode="sdk-only",
        team_id="team-x",
        parent_agent_id="parent-y",
    )
    try:
        # Lineage is dropped against an old core, but registration still succeeds
        # via the 4-arg legacy signature — no exception.
        assert legacy_client.register_calls == [("legacy-agent", "legacy-agent", "python", _GRPC_ENDPOINT)]
    finally:
        context.shutdown()


def test_init_assembly_lineage_values_round_trip_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unicode / long lineage ids are forwarded to register without mangling."""
    runtime_client = FakeRuntimeClient(decision="allow")
    install_fake_core(monkeypatch, runtime_client)
    _no_network(monkeypatch)
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **_kwargs: [])

    team = "équipe-paiements-🌐"
    parent = "parent-" + ("a" * 200)
    context = init_assembly(
        gateway_url=_GW_URL,
        api_key=_API_KEY,
        agent_id="unicode-child",
        mode="sdk-only",
        team_id=team,
        parent_agent_id=parent,
    )
    try:
        assert runtime_client.register_calls == [
            ("unicode-child", "unicode-child", "python", _GRPC_ENDPOINT, team, parent)
        ]
    finally:
        context.shutdown()


def test_connect_forwards_agent_id_and_installed_package_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """connect_runtime_client forwards the agent id and the installed PyPI
    package version into the native ``connect`` so the language-package version
    (not the crate version) is signed into the handshake (AAASM-3683)."""
    from agent_assembly.core import runtime_interceptor

    runtime_client = FakeRuntimeClient(decision="allow")
    install_fake_core(monkeypatch, runtime_client)
    # Pin the resolved package version deterministically.
    monkeypatch.setattr(runtime_interceptor, "_sdk_version", lambda: "7.8.9")

    result = runtime_interceptor.connect_runtime_client("agent-vers")

    assert result is runtime_client
    assert runtime_client.connect_args is not None
    _socket, agent_id, sdk_version = runtime_client.connect_args
    assert agent_id == "agent-vers"
    assert sdk_version == "7.8.9"


def test_connect_passes_none_version_when_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the package version cannot be resolved, ``None`` is forwarded so the
    native shim falls back to the crate version (no regression, AAASM-3683)."""
    from agent_assembly.core import runtime_interceptor

    runtime_client = FakeRuntimeClient(decision="allow")
    install_fake_core(monkeypatch, runtime_client)
    monkeypatch.setattr(runtime_interceptor, "_sdk_version", lambda: None)

    runtime_interceptor.connect_runtime_client("agent-novers")

    assert runtime_client.connect_args is not None
    _socket, _agent_id, sdk_version = runtime_client.connect_args
    assert sdk_version is None


def test_sdk_version_reads_installed_distribution_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_sdk_version prefers importlib.metadata.version('agent-assembly')."""
    import importlib.metadata

    from agent_assembly.core import runtime_interceptor

    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "3.2.1")
    assert runtime_interceptor._sdk_version() == "3.2.1"


def test_sdk_version_falls_back_to_module_version_when_metadata_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the distribution is not installed (e.g. an editable checkout that was
    never ``pip install``-ed), ``_sdk_version`` falls back to the in-tree
    ``agent_assembly.__version__`` rather than returning ``None`` (AAASM-3683)."""
    import importlib.metadata

    import agent_assembly
    from agent_assembly.core import runtime_interceptor

    def _raise_not_found(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(_name)

    monkeypatch.setattr(importlib.metadata, "version", _raise_not_found)
    monkeypatch.setattr(agent_assembly, "__version__", "9.9.9-editable", raising=False)

    assert runtime_interceptor._sdk_version() == "9.9.9-editable"


def test_sdk_version_returns_none_when_no_version_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If neither the distribution metadata nor ``agent_assembly.__version__`` can
    be resolved, ``_sdk_version`` returns ``None`` so the native shim falls back
    to the crate version instead of raising (AAASM-3683)."""
    import importlib.metadata

    import agent_assembly
    from agent_assembly.core import runtime_interceptor

    def _raise_not_found(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(_name)

    monkeypatch.setattr(importlib.metadata, "version", _raise_not_found)
    # Remove the in-tree fallback so ``from agent_assembly import __version__`` fails.
    monkeypatch.delattr(agent_assembly, "__version__", raising=False)

    assert runtime_interceptor._sdk_version() is None


def test_connect_falls_back_to_legacy_signature_on_typeerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Against an older native build whose ``connect`` predates the
    ``agent_id`` / ``sdk_version`` parameters, the three-arg call raises
    ``TypeError`` and the SDK retries with the legacy single-arg signature so a
    connection is still established (AAASM-3683)."""
    from agent_assembly.core import runtime_interceptor

    legacy_client = object()
    calls: list[tuple[Any, ...]] = []

    def _legacy_connect(*args: Any) -> Any:
        calls.append(args)
        # Old native build only accepts the socket path.
        if len(args) != 1:
            raise TypeError("connect() takes 1 positional argument")
        return legacy_client

    install_fake_core_with_connect(monkeypatch, _legacy_connect)
    monkeypatch.setattr(runtime_interceptor, "_sdk_version", lambda: "1.2.3")

    result = runtime_interceptor.connect_runtime_client("legacy-agent")

    # The three-arg attempt is made first, then the one-arg legacy retry.
    assert len(calls) == 2
    assert len(calls[0]) == 3
    assert len(calls[1]) == 1
    assert result is legacy_client


def test_connect_returns_none_when_legacy_retry_also_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the legacy single-arg ``connect`` retry also raises (e.g. the socket is
    unreachable), ``connect_runtime_client`` returns ``None`` rather than
    propagating, so there is simply no native fast path (AAASM-3683)."""
    from agent_assembly.core import runtime_interceptor

    def _always_failing_connect(*args: Any) -> Any:
        if len(args) != 1:
            raise TypeError("connect() takes 1 positional argument")
        raise OSError("socket unreachable")

    install_fake_core_with_connect(monkeypatch, _always_failing_connect)
    monkeypatch.setattr(runtime_interceptor, "_sdk_version", lambda: "1.2.3")

    assert runtime_interceptor.connect_runtime_client("legacy-agent") is None


def test_connect_returns_none_on_generic_connect_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-``TypeError`` failure from the native ``connect`` (e.g. the runtime
    socket is unreachable) yields ``None`` rather than raising (AAASM-3683)."""
    from agent_assembly.core import runtime_interceptor

    def _failing_connect(*_args: Any) -> Any:
        raise OSError("runtime socket unreachable")

    install_fake_core_with_connect(monkeypatch, _failing_connect)
    monkeypatch.setattr(runtime_interceptor, "_sdk_version", lambda: "1.2.3")

    assert runtime_interceptor.connect_runtime_client("agent-x") is None


def test_init_assembly_deny_blocks_tool_via_interceptor(monkeypatch: pytest.MonkeyPatch) -> None:
    """A native ``deny`` makes the adapter interceptor's check_tool_start block."""
    runtime_client = FakeRuntimeClient(decision="deny", reason="policy violation")
    install_fake_core(monkeypatch, runtime_client)
    _no_network(monkeypatch)

    adapter = _CapturingAdapter()
    monkeypatch.setattr(core_assembly, "_register_adapters", _patched_register_adapters(adapter))

    context = init_assembly(
        gateway_url=_GW_URL,
        api_key=_API_KEY,
        agent_id="agent-deny",
        mode="sdk-only",
        enforcement_mode="enforce",
    )
    try:
        assert adapter.interceptor is not None
        interceptor: Any = adapter.interceptor
        result = interceptor.check_tool_start(
            serialized={"name": "web_search"},
            input_str="q",
            tool_name="web_search",
            args={"q": "x"},
        )
        assert result == {"status": "deny", "reason": "policy violation"}
    finally:
        context.shutdown()


def test_observe_mode_swallows_register_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Under observe a native registration failure does not abort init."""
    runtime_client = FakeRuntimeClient(decision="allow")
    runtime_client.register_should_raise = RuntimeError("gateway down")
    install_fake_core(monkeypatch, runtime_client)
    _no_network(monkeypatch)
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **_kwargs: [])

    context = init_assembly(
        gateway_url=_GW_URL,
        api_key=_API_KEY,
        agent_id="agent-observe",
        mode="sdk-only",
        enforcement_mode="observe",
    )
    context.shutdown()


def test_enforce_mode_propagates_register_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Under enforce a native registration failure aborts init (fail closed)."""
    runtime_client = FakeRuntimeClient(decision="allow")
    runtime_client.register_should_raise = RuntimeError("gateway rejected")
    install_fake_core(monkeypatch, runtime_client)
    _no_network(monkeypatch)
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **_kwargs: [])

    with pytest.raises(ConfigurationError, match="Failed to initialize assembly runtime"):
        init_assembly(
            gateway_url=_GW_URL,
            api_key=_API_KEY,
            agent_id="agent-enforce",
            mode="sdk-only",
            enforcement_mode="enforce",
        )


def _patched_register_adapters(adapter: _CapturingAdapter) -> object:
    """Build a stand-in for ``_register_adapters`` that drives the real
    interceptor builder and registers the capturing adapter with it."""

    def _impl(
        *,
        client: object,
        process_agent_id: str,
        enforcement_mode: str | None = None,
        runtime_client: object | None = None,
        native_available: bool = False,
    ) -> list[FrameworkAdapter]:
        interceptor = build_governance_interceptor(
            client,
            process_agent_id,
            enforcement_mode,
            runtime_client=runtime_client,
            native_available=native_available,
        )
        adapter.register_hooks(interceptor)
        return [adapter]

    return _impl


def test_successful_register_marks_context_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful native register sets ``ctx.registered`` True (AAASM-4547)."""
    runtime_client = FakeRuntimeClient(decision="allow")
    install_fake_core(monkeypatch, runtime_client)
    _no_network(monkeypatch)
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **_kwargs: [])

    context = init_assembly(gateway_url=_GW_URL, api_key=_API_KEY, agent_id="reg-ok", mode="sdk-only")
    try:
        assert context.registered is True
    finally:
        context.shutdown()


def test_native_absent_warns_loudly_and_marks_unregistered(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With the native extension absent, init no longer silently skips register:
    it warns loudly and reports ``ctx.registered`` False (AAASM-4547)."""
    monkeypatch.setattr(core_assembly, "_native_core_available", lambda: False)
    _no_network(monkeypatch)
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **_kwargs: [])

    context = init_assembly(gateway_url=_GW_URL, api_key=_API_KEY, agent_id="no-native", mode="sdk-only")
    try:
        assert context.registered is False
        err = capsys.readouterr().err
        assert "NOT registered" in err
        assert "agent_assembly._core" in err
        assert "AAASM-4547" in err
    finally:
        context.shutdown()


def test_native_present_but_no_runtime_client_warns_and_marks_unregistered(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Native present but the runtime client could not be established (e.g. a
    distrusted socket) → warn + ``registered`` False, not a silent skip (AAASM-4547)."""
    monkeypatch.setattr(core_assembly, "_native_core_available", lambda: True)
    monkeypatch.setattr(core_assembly, "connect_runtime_client", lambda _agent_id: None)
    _no_network(monkeypatch)
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **_kwargs: [])

    context = init_assembly(gateway_url=_GW_URL, api_key=_API_KEY, agent_id="no-client", mode="sdk-only")
    try:
        assert context.registered is False
        assert "NOT registered" in capsys.readouterr().err
    finally:
        context.shutdown()


def test_register_failure_under_observe_warns_and_marks_unregistered(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Under observe a register failure no longer aborts init, but it is now loud
    and reflected in ``ctx.registered`` False rather than swallowed (AAASM-4547)."""
    runtime_client = FakeRuntimeClient(decision="allow")
    runtime_client.register_should_raise = RuntimeError("gateway gRPC endpoint is unreachable")
    install_fake_core(monkeypatch, runtime_client)
    _no_network(monkeypatch)
    monkeypatch.setattr(core_assembly, "_register_adapters", lambda **_kwargs: [])

    context = init_assembly(
        gateway_url=_GW_URL,
        api_key=_API_KEY,
        agent_id="reg-fail",
        mode="sdk-only",
        enforcement_mode="observe",
    )
    try:
        assert context.registered is False
        err = capsys.readouterr().err
        assert "NOT registered" in err
        assert "registration failed" in err
    finally:
        context.shutdown()
