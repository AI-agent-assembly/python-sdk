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
from agent_assembly.exceptions import ConfigurationError

from ._fake_core import FakeRuntimeClient, install_fake_core

_GW_URL = "http://gateway.test"
_API_KEY = "test-key"


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
        assert runtime_client.register_calls == [("agent-7", "agent-7", "python", None, None, None)]
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
        assert runtime_client.register_calls == [("child-1", "child-1", "python", None, "team-payments", "parent-42")]
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
        assert runtime_client.register_calls == [("team-only", "team-only", "python", None, "team-billing", None)]
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
        assert runtime_client.register_calls == [("parent-only", "parent-only", "python", None, None, "orchestrator-1")]
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
        assert runtime_client.register_calls == [("solo", "solo", "python", None, None, None)]
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
        assert runtime_client.register_calls == [("unicode-child", "unicode-child", "python", None, team, parent)]
    finally:
        context.shutdown()


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
