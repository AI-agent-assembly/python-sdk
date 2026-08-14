"""Reusable fakes for the native ``agent_assembly._core`` extension.

These let the SDK wiring tests (AAASM-3402) exercise the native register /
query_policy path without a built extension or a running ``aa-runtime``: the
``FakeRuntimeClient`` records ``register`` calls and returns a canned
``query_policy`` decision, and ``install_fake_core`` swaps a module exposing a
``RuntimeClient`` whose ``connect`` yields one into ``sys.modules``.
"""

from __future__ import annotations

import json
import sys
import types
from collections.abc import Callable
from typing import Any

import pytest


class FakeRuntimeClient:
    """Stand-in for the native ``RuntimeClient`` (register + query_policy)."""

    def __init__(self, decision: str = "allow", reason: str = "") -> None:
        self._decision = decision
        self._reason = reason
        self.register_calls: list[tuple[str, str, str, str | None, str | None, str | None]] = []
        self.query_calls: list[tuple[Any, ...]] = []
        self.register_should_raise: Exception | None = None
        self.sent_events: list[Any] = []
        # Set by install_fake_core's connect to the (socket_path, agent_id,
        # sdk_version) it was called with (AAASM-3683).
        self.connect_args: tuple[str, str | None, str | None] | None = None

    def register(
        self,
        agent_id: str,
        name: str,
        framework: str,
        gateway_endpoint: str | None = None,
        team_id: str | None = None,
        parent_agent_id: str | None = None,
    ) -> str:
        if self.register_should_raise is not None:
            raise self.register_should_raise
        self.register_calls.append((agent_id, name, framework, gateway_endpoint, team_id, parent_agent_id))
        return "policy-id-001"

    def query_policy(
        self,
        agent_id: str,
        action_type: str,
        tool_name: str | None = None,
        tool_args_json: str | None = None,
    ) -> dict[str, str]:
        self.query_calls.append((agent_id, action_type, tool_name, tool_args_json))
        return {"decision": self._decision, "reason": self._reason}

    def send_event(self, event: Any) -> None:
        """The native audit channel (AAASM-5750).

        Present because the real shim has it and the SDK reads for it by name to
        decide whether it can record at all: a double missing it makes every
        interceptor built over it declare ``absent``, which would quietly turn
        the forwarding path off in any test using this fake.
        """
        self.sent_events.append(getattr(event, "payload_json", event))

    def close(self) -> None:
        return None


class LegacyRuntimeClient:
    """Stand-in for an older native build whose ``register`` predates the
    ``team_id`` / ``parent_agent_id`` parameters (AAASM-3415).

    Its ``register`` only accepts the legacy positional signature, so calling it
    with the lineage kwargs raises ``TypeError`` — exercising the SDK's
    backwards-compatible fallback in ``register_agent``.
    """

    def __init__(self) -> None:
        self.register_calls: list[tuple[str, str, str, str | None]] = []

    def register(
        self,
        agent_id: str,
        name: str,
        framework: str,
        gateway_endpoint: str | None = None,
    ) -> str:
        self.register_calls.append((agent_id, name, framework, gateway_endpoint))
        return "policy-id-legacy"

    def close(self) -> None:
        return None


#: Fields ``aa_core::AuditEntry`` requires, mirrored from the struct the real
#: ``GovernanceEvent`` constructor deserializes into. Everything else on that
#: struct is ``Option`` / ``default``; these are not, so a payload missing one is
#: rejected by the native extension.
AUDIT_ENTRY_REQUIRED_FIELDS = frozenset(
    {"seq", "timestamp_ns", "event_type", "agent_id", "session_id", "payload", "previous_hash", "entry_hash"}
)


class FakeGovernanceEvent:
    """Stand-in for the native ``GovernanceEvent`` wrapper.

    It replicates the one behaviour the SDK depends on and could get wrong: the
    real constructor deserializes its argument as ``aa_core::AuditEntry`` JSON and
    raises ``ValueError`` when that fails, so a payload builder that emits the
    wrong shape fails at the boundary rather than silently. A double that
    accepted any string would make every "the record crossed" assertion pass over
    a payload the real extension rejects.

    It is a **replica of the contract, not the validator**. It checks the
    required field set, not serde's full type discipline, so it cannot prove the
    real constructor accepts a given payload — only that an obviously wrong one
    is caught. The real constructor is exercised against this SDK's builder in
    ``test/integration/test_native_core_runtime.py``, which runs only where the
    extension is built.
    """

    def __init__(self, payload_json: str) -> None:
        try:
            decoded = json.loads(payload_json)
        except ValueError as error:
            raise ValueError(f"GovernanceEvent payload must be serialized aa_core::AuditEntry JSON: {error}") from error
        if not isinstance(decoded, dict):
            raise ValueError("GovernanceEvent payload must be serialized aa_core::AuditEntry JSON: not an object")
        missing = AUDIT_ENTRY_REQUIRED_FIELDS - decoded.keys()
        if missing:
            raise ValueError(
                f"GovernanceEvent payload must be serialized aa_core::AuditEntry JSON: missing {sorted(missing)}"
            )
        self.payload_json = payload_json


def install_fake_core(
    monkeypatch: pytest.MonkeyPatch,
    runtime_client: Any,
) -> Any:
    """Install a fake ``agent_assembly._core`` whose ``RuntimeClient.connect``
    returns ``runtime_client``. Returns the same client for assertions.

    ``connect`` accepts the AAASM-3683 ``agent_id`` / ``sdk_version`` arguments
    and records them on ``runtime_client.connect_args`` so callers can assert the
    installed package version is forwarded into the handshake.
    """

    class _ConnectingRuntimeClient:
        @staticmethod
        def connect(_socket_path: str, agent_id: str | None = None, sdk_version: str | None = None) -> Any:
            runtime_client.connect_args = (_socket_path, agent_id, sdk_version)
            return runtime_client

    fake_core = types.ModuleType("agent_assembly._core")
    fake_core.RuntimeClient = _ConnectingRuntimeClient  # type: ignore[attr-defined]
    fake_core.GovernanceEvent = FakeGovernanceEvent  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "agent_assembly._core", fake_core)
    return runtime_client


def install_fake_core_with_connect(
    monkeypatch: pytest.MonkeyPatch,
    connect: Callable[..., Any],
) -> None:
    """Install a fake ``agent_assembly._core`` whose ``RuntimeClient.connect`` is
    the supplied callable.

    Lets a test drive the connect path against a native build that, for example,
    predates the AAASM-3683 ``sdk_version`` parameter (``connect`` raising
    ``TypeError`` for the extra argument) or fails outright.
    """

    runtime_client_cls = type(
        "_CustomConnectRuntimeClient",
        (),
        {"connect": staticmethod(connect)},
    )

    fake_core = types.ModuleType("agent_assembly._core")
    fake_core.RuntimeClient = runtime_client_cls  # type: ignore[attr-defined]
    fake_core.GovernanceEvent = FakeGovernanceEvent  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "agent_assembly._core", fake_core)
