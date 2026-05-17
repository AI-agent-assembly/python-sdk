"""Unit tests for the `agent_assembly.types` dataclasses (AAASM-1435).

Covers `AuditEvent` + `CallStackNode` — the Python-friendly mirrors of
the proto messages added in AAASM-1419.
"""

from __future__ import annotations

import dataclasses

import pytest

from agent_assembly import AuditEvent, CallStackNode


def test_call_stack_node_required_fields() -> None:
    node = CallStackNode(id="n0", kind="llm", label="gpt-4o")
    assert node.id == "n0"
    assert node.kind == "llm"
    assert node.label == "gpt-4o"
    assert node.latency_ms is None
    assert node.children == []


def test_call_stack_node_with_latency_and_children() -> None:
    child = CallStackNode(id="n1", kind="tool", label="gmail.send", latency_ms=120)
    parent = CallStackNode(
        id="n0", kind="llm", label="gpt-4o", latency_ms=300, children=[child]
    )
    assert parent.children[0] is child
    assert parent.children[0].latency_ms == 120


def test_call_stack_node_is_frozen() -> None:
    node = CallStackNode(id="n0", kind="llm", label="gpt-4o")
    with pytest.raises(dataclasses.FrozenInstanceError):
        node.id = "n2"  # type: ignore[misc]


def test_audit_event_minimal_construction_defaults_call_stack_to_empty() -> None:
    event = AuditEvent(
        event_id="evt-1",
        agent_id="support-agent",
        action_type="llm_call",
        decision="allow",
    )
    assert event.call_stack == []
    assert event.labels == {}
    assert event.trace_id == ""
    assert event.span_id == ""
    assert event.parent_span_id == ""


def test_audit_event_with_populated_call_stack_tree() -> None:
    stack = [
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
                        CallStackNode(id="n2", kind="result", label="200 OK"),
                    ],
                ),
            ],
        ),
    ]
    event = AuditEvent(
        event_id="evt-1",
        agent_id="support-agent",
        action_type="llm_call",
        decision="allow",
        trace_id="trace-1",
        span_id="span-1",
        call_stack=stack,
    )
    assert event.call_stack[0].kind == "llm"
    assert event.call_stack[0].children[0].label == "gmail.send"
    assert event.call_stack[0].children[0].children[0].kind == "result"
    assert event.call_stack[0].children[0].children[0].latency_ms is None


def test_audit_event_is_frozen() -> None:
    event = AuditEvent(event_id="e", agent_id="a", action_type="llm_call", decision="allow")
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.event_id = "e2"  # type: ignore[misc]


def test_top_level_imports_resolve_to_types_module() -> None:
    from agent_assembly.types import AuditEvent as TypesAuditEvent
    from agent_assembly.types import CallStackNode as TypesCallStackNode

    assert AuditEvent is TypesAuditEvent
    assert CallStackNode is TypesCallStackNode
