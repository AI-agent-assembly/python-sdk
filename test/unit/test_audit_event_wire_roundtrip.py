"""Wire-protocol round-trip tests for `AuditEvent` / `CallStackNode`.

Covers the AAASM-1442 bridge between the pure-Python dataclasses in
`agent_assembly.types` and the Rust `aa_proto` encoder via PyO3.

All tests skip cleanly when the native `agent_assembly._core` module is
not built (pure-Python install), matching the existing
`test/bench/test_report_llm_call_roundtrip.py` convention.
"""

from __future__ import annotations

import pytest

from agent_assembly import AuditEvent, CallStackNode

pytest.importorskip(
    "agent_assembly._core",
    reason="native _core module not built (requires maturin develop)",
)


def test_three_level_call_stack_round_trips_without_data_loss() -> None:
    original = AuditEvent(
        event_id="evt-1",
        agent_id="support-agent",
        action_type="llm_call",
        decision="allow",
        trace_id="trace-1",
        span_id="span-1",
        parent_span_id="span-0",
        labels={"team": "platform", "env": "prod"},
        call_stack=[
            CallStackNode(
                id="n0",
                kind="llm",
                label="gpt-4o",
                latency_ms=300,
                children=[
                    CallStackNode(
                        id="n1",
                        kind="tool",
                        label="gmail.send",
                        latency_ms=120,
                        children=[
                            CallStackNode(
                                id="n2",
                                kind="result",
                                label="200 OK",
                                latency_ms=5,
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )

    decoded = AuditEvent.from_wire_bytes(original.to_wire_bytes())

    assert decoded == original


def test_legacy_payload_without_call_stack_decodes_to_empty_list() -> None:
    """Events emitted before AAASM-1419 added `call_stack` must still decode.

    Proto3 elides default-valued repeated fields on the wire, so an
    event with `call_stack=[]` produces bytes indistinguishable from
    a pre-1419 event that did not set the field at all. The decoded
    dataclass must surface this as the empty list (not None or a
    missing attribute).
    """
    original = AuditEvent(
        event_id="evt-legacy",
        agent_id="legacy-agent",
        action_type="tool_call",
        decision="deny",
    )

    decoded = AuditEvent.from_wire_bytes(original.to_wire_bytes())

    assert decoded.call_stack == []
    assert decoded == original


def test_call_stack_node_kind_outside_literal_round_trips_unchanged() -> None:
    """`kind` is proto `string`, not enum — the bridge accepts any value.

    The Python `CallStackNodeKind` `Literal` narrows the type for
    Python authors but does not restrict what arrives from a future
    producer that emits a new node category. The wire layer must
    preserve such values verbatim instead of normalising them.
    """
    original = AuditEvent(
        event_id="evt-invalid-kind",
        agent_id="future-agent",
        action_type="llm_call",
        decision="allow",
        call_stack=[
            CallStackNode(
                id="n0",
                kind="unknown",  # type: ignore[arg-type]
                label="future-node-type",
            ),
        ],
    )

    decoded = AuditEvent.from_wire_bytes(original.to_wire_bytes())

    assert decoded.call_stack[0].kind == "unknown"  # type: ignore[comparison-overlap]  # round-trip yields out-of-enum "unknown" wire fallback
    assert decoded == original
