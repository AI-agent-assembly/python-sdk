"""Type-checking example for the Agent Assembly Python SDK.

Demonstrates annotating against the SDK's public, fully-typed surface. The SDK
ships a PEP 561 ``py.typed`` marker, so a static type checker resolves these
types directly from the installed package — no stub packages required.

Verify::

    uv run mypy examples/type_checking/type_checking_example.py
    uv run python examples/type_checking/type_checking_example.py
"""

from __future__ import annotations

from agent_assembly.models import AgentConfig
from agent_assembly.types import AuditEvent, CallStackNode, CallStackNodeKind


def build_agent_config() -> AgentConfig:
    """Construct a typed agent configuration model."""
    return AgentConfig(
        agent_id="my-agent-001",
        name="My AI Agent",
        description="A sample agent governed by Agent Assembly.",
        version="1.0.0",
    )


def build_call_stack() -> list[CallStackNode]:
    """Build a small hierarchical call stack with typed node kinds."""
    tool_kind: CallStackNodeKind = "tool"
    result_kind: CallStackNodeKind = "result"
    return [
        CallStackNode(
            id="step-1",
            kind=tool_kind,
            label="whoami",
            latency_ms=12,
            children=[CallStackNode(id="step-1.1", kind=result_kind, label="alice")],
        )
    ]


def build_audit_event() -> AuditEvent:
    """Construct a typed audit event referencing the call stack above."""
    return AuditEvent(
        event_id="018f5b2c-0000-7000-8000-000000000001",
        agent_id="my-agent-001",
        action_type="tool_call",
        decision="allow",
        labels={"team": "engineering"},
        call_stack=build_call_stack(),
    )


def main() -> None:
    """Run the typed example end to end."""
    print("=== Agent Assembly type-checking example ===\n")

    config = build_agent_config()
    print(f"Agent: {config.name} ({config.agent_id}) v{config.version}")

    event = build_audit_event()
    print(f"Audit event {event.event_id}: {event.action_type} -> {event.decision}")
    print(f"Call-stack nodes: {len(event.call_stack)}")

    print("\n✓ Type-checking example completed successfully!")


if __name__ == "__main__":
    main()
