"""
Type definitions for the Agent Assembly Python SDK.

This module provides centralized type aliases and type definitions following
PEP 561, PEP 484, PEP 585, and PEP 695 standards for static type checking with MyPy.

Type aliases use the modern `type` statement (PEP 695) introduced in Python 3.12,
which provides better type inference and cleaner syntax compared to TypeAlias.

Type Hierarchy:
    - Agent types: Agent identity and configuration types
    - Policy types: Policy enforcement and governance types
    - Event types: Audit logging and event handling types
    - Gateway types: Communication with governance gateway
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, cast

# ── Event types (AAASM-1435) ──────────────────────────────────────────────────

CallStackNodeKind = Literal["llm", "tool", "result"]
"""Discriminator for a [`CallStackNode`] — open-ended on the wire (proto uses
`string kind`) but typed here as a `Literal` for the three values the
dashboard currently renders."""


@dataclass(frozen=True, slots=True)
class CallStackNode:
    """One node in the hierarchical call stack attached to an [`AuditEvent`].

    Mirrors the proto `assembly.audit.v1.CallStackNode` message added in
    AAASM-1419. Field names match the wire-protocol's snake_case so the
    dataclass can be constructed directly from a decoded payload without an
    intermediate naming transform.

    Attributes:
        id: Stable identifier for this node within the call stack.
        kind: Node category — one of ``"llm"``, ``"tool"``, or ``"result"``.
        label: Human-readable label rendered by downstream UI.
        latency_ms: Step-local latency in milliseconds, or `None` when the
            producer did not record a duration.
        children: Recursive descent — nested calls produced by this step.
            Empty list (default) when the node has no children.
    """

    id: str
    kind: CallStackNodeKind
    label: str
    latency_ms: int | None = None
    children: list[CallStackNode] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """A single governance-relevant occurrence in the gateway audit trail.

    Python-friendly subset of the proto `assembly.audit.v1.AuditEvent`
    message. Field names match the wire-protocol's snake_case so the
    dataclass can be constructed directly from a decoded payload.

    Out of scope today (tracked under separate follow-up Tasks):
      * The ``detail`` oneof (`LLMCallDetail` / `ToolCallDetail` /
        `FileOpDetail` / `NetworkCallDetail` / `ProcessExecDetail` /
        `PolicyViolation` / `ApprovalEvent`).
      * The lineage block (`root_agent_id`, `parent_agent_id`, `team_id`,
        `session_id`, `delegation_reason`, `spawned_by_tool`, `depth`).

    This class exists today to surface the new ``call_stack`` field added
    by AAASM-1419 to SDK consumers. Round-tripping into the gateway via the
    wire encoder remains the Rust FFI layer's responsibility.

    Attributes:
        event_id: Unique identifier for this audit record (UUID v7).
        agent_id: Identity string of the agent that produced this event.
        action_type: High-level action category (e.g. ``"llm_call"``,
            ``"tool_call"``, ``"file_op"``). Open-ended on the wire.
        decision: Policy engine verdict (e.g. ``"allow"``, ``"deny"``,
            ``"redact"``).
        trace_id: Distributed tracing run-level identifier. Empty when
            unset.
        span_id: Distributed tracing action-level identifier. Empty when
            unset.
        parent_span_id: Distributed tracing parent span identifier. Empty
            when this is a root span.
        labels: Arbitrary key/value labels attached at event creation.
        call_stack: Hierarchical record of LLM / tool / result steps that
            led to this event. Empty list (default) when the producer did
            not record a stack. Renders inline beneath an expanded Live
            Ops row in the dashboard.
    """

    event_id: str
    agent_id: str
    action_type: str
    decision: str
    trace_id: str = ""
    span_id: str = ""
    parent_span_id: str = ""
    labels: dict[str, str] = field(default_factory=dict)
    call_stack: list[CallStackNode] = field(default_factory=list)

    def to_wire_bytes(self) -> bytes:
        """Encode this event to `aa_proto::AuditEvent` wire bytes.

        Requires the native `agent_assembly._core` extension. Raises
        `ImportError` when the SDK is installed without the native
        wheel (pure-Python mode).
        """
        try:
            from agent_assembly._core import audit_event_to_wire_bytes  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "AuditEvent.to_wire_bytes() requires the native "
                "agent_assembly._core extension; reinstall with the "
                "native wheel or run `maturin develop` in native/aa-ffi-python/."
            ) from exc
        return cast(bytes, audit_event_to_wire_bytes(self))

    @classmethod
    def from_wire_bytes(cls, data: bytes) -> AuditEvent:
        """Decode `aa_proto::AuditEvent` wire bytes into a dataclass.

        Requires the native `agent_assembly._core` extension. Raises
        `ImportError` when the SDK is installed without the native
        wheel.
        """
        try:
            from agent_assembly._core import audit_event_from_wire_bytes
        except ImportError as exc:
            raise ImportError(
                "AuditEvent.from_wire_bytes() requires the native "
                "agent_assembly._core extension; reinstall with the "
                "native wheel or run `maturin develop` in native/aa-ffi-python/."
            ) from exc
        return cast(AuditEvent, audit_event_from_wire_bytes(data))


__all__ = [
    "AuditEvent",
    "CallStackNode",
    "CallStackNodeKind",
]
