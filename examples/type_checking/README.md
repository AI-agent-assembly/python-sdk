# Type-checking example

A runnable example showing how to annotate against the Agent Assembly Python SDK's public,
fully-typed surface. The SDK ships a PEP 561 `py.typed` marker, so type checkers resolve these
types directly from the installed package — no stub packages needed.

## Run it

```bash
# Type-check the example
uv run mypy examples/type_checking/type_checking_example.py

# Execute it (prints a small typed audit event + agent config)
uv run python examples/type_checking/type_checking_example.py
```

Expected output:

```
=== Agent Assembly type-checking example ===

Agent: My AI Agent (my-agent-001) v1.0.0
Audit event 018f5b2c-0000-7000-8000-000000000001: tool_call -> allow
Call-stack nodes: 1

✓ Type-checking example completed successfully!
```

## What it demonstrates

- Importing typed data classes from their defining submodules
  (`agent_assembly.types`, `agent_assembly.models`).
- Constructing `AgentConfig`, `AuditEvent`, and a nested `CallStackNode` tree with the
  `CallStackNodeKind` literal — all statically checked.

See the [Type checking guide](https://docs.agent-assembly.com/python-sdk/latest/usage/type-checking/)
for the full public type surface and how to type-check your own integration.
