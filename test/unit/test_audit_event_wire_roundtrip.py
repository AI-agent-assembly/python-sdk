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
