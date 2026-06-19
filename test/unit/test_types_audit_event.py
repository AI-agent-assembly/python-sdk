"""Unit tests for the `agent_assembly.types` dataclasses (AAASM-1435).

Covers `AuditEvent` + `CallStackNode` — the Python-friendly mirrors of
the proto messages added in AAASM-1419.
"""

from __future__ import annotations

import dataclasses

import pytest

from agent_assembly import AuditEvent, CallStackNode
from agent_assembly.core.runtime_interceptor import _native_core_available

# The native `_core` extension implements the wire codec; these import-error
# guards only fire in pure-Python mode where it is absent (AAASM-3435).
_NATIVE_CORE_PRESENT = _native_core_available()
_requires_no_native_core = pytest.mark.skipif(
    _NATIVE_CORE_PRESENT,
    reason="native `_core` is present; the import-error path only exists without it",
)


def test_call_stack_node_required_fields() -> None:
    node = CallStackNode(id="n0", kind="llm", label="gpt-4o")
    assert node.id == "n0"
    assert node.kind == "llm"
    assert node.label == "gpt-4o"
    assert node.latency_ms is None
    assert node.children == []


def test_call_stack_node_with_latency_and_children() -> None:
    child = CallStackNode(id="n1", kind="tool", label="gmail.send", latency_ms=120)
    parent = CallStackNode(id="n0", kind="llm", label="gpt-4o", latency_ms=300, children=[child])
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


@_requires_no_native_core
def test_to_wire_bytes_raises_helpful_import_error_without_native_core() -> None:
    """In pure-Python mode the native `_core` extension is absent, so the
    encode path raises ImportError with a maturin/reinstall hint."""
    event = AuditEvent(event_id="e", agent_id="a", action_type="llm_call", decision="allow")
    with pytest.raises(ImportError) as exc_info:
        event.to_wire_bytes()

    message = str(exc_info.value)
    assert "to_wire_bytes()" in message
    assert "maturin develop" in message


@_requires_no_native_core
def test_from_wire_bytes_raises_helpful_import_error_without_native_core() -> None:
    """The decode path raises the same kind of guidance when `_core` is absent."""
    with pytest.raises(ImportError) as exc_info:
        AuditEvent.from_wire_bytes(b"\x00\x01")

    message = str(exc_info.value)
    assert "from_wire_bytes()" in message
    assert "native" in message
