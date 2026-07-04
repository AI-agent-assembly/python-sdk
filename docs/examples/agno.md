# Agno

Integrates Agent Assembly with [Agno](https://docs.agno.com/) (formerly Phidata) to enforce governance policy on tool calls before they execute.

## What this example demonstrates

- Initializing Agent Assembly with `init_assembly()` in offline `sdk-only` mode.
- Installing Agno tool-level governance via the **native Agno adapter** — `AgnoPatch` patches `agno.tools.function.FunctionCall.execute`, the single chokepoint every Agno function-tool call runs through.
- Running an **allowed** tool call (`get_weather`), another **allowed** tool call (`summarize_docs`), and a **denied** tool call (`execute_sql`, blocked by policy rule `deny_arbitrary_execution`).
- How a denied tool short-circuits entirely — its body never runs — and returns a failure `FunctionExecutionResult` instead of a result.
- Driving genuine Agno `@tool` functions exactly as an Agno `Agent` does — `FunctionCall(...).execute()` — with no gateway, API key, or live LLM.

## The framework / library

[Agno](https://docs.agno.com/) (formerly Phidata) is the agent framework governed in this example. Agno has a **native Agent Assembly adapter** (`agent_assembly.adapters.agno`), so governance is wired by patching Agno's own tool-execution chokepoint rather than wrapping individual tools.

Version pins (from `pyproject.toml`):

| Dependency | Version |
|---|---|
| `agno` | `>=2.0.0` |
| `agent-assembly` | `>=0.0.1rc3` (the release that ships the Agno adapter) |
| Python | `>=3.12` |

## How it works

`init_assembly()` is opened as a context manager in offline `sdk-only` mode with the agent id `agno-demo-agent`:

```python
with init_assembly(
    gateway_url=gateway_url,
    api_key=api_key,
    agent_id="agno-demo-agent",
    mode="sdk-only",
) as ctx:
    ...
```

**Hook point.** The Agno adapter governs Agno by patching `agno.tools.function.FunctionCall.execute` (and its async counterpart `aexecute`) — the single chokepoint every Agno function-tool call runs through. Every tool an Agno agent invokes therefore passes through policy *before* its body executes.

**Offline note.** In production, `init_assembly()` auto-detects Agno and wires the live runtime as the interceptor automatically. In this offline `sdk-only` demo there is no live runtime, so `init_assembly()` installs a no-op hook; the example reverts it and re-applies the hook wired to a local `LocalPolicyEngine` so the demo shows real allow/deny decisions without a gateway (the patch is idempotent, so the no-op hook is reverted first):

```python
AgnoPatch(policy).revert()
patch = AgnoPatch(policy)
assert patch.apply()
```

The adapter calls `check_tool_start` on `LocalPolicyEngine` (`src/policy.py`), which returns a decision dict in the gateway wire format `{"status": "allow"}` or `{"status": "deny", "reason": ...}`. `execute_sql` and `run_shell_command` are denied (arbitrary execution); everything else is allowed. The engine runs fail-closed, so an unknown verdict denies rather than allows.

**Deny behavior.** When `execute_sql` is denied, `FunctionCall.execute()` returns a `FunctionExecutionResult` with `status == "failure"` whose error carries the `[BLOCKED by governance policy]` marker and the `deny_arbitrary_execution` rule name. The tool's body never runs — the example proves this with a side-effect sink (`SQL_EXECUTIONS`) that stays empty for a denied call, the negative control that would fail if governance were a no-op.

## Prerequisites & running it

See [Preparing the runtime environment](preparing-the-runtime-environment.md) for the shared prerequisites.

Then run the example (offline — no API key and no running gateway required):

```bash
cd python/agno-tool-policy
uv sync --extra dev
uv run python src/main.py
```

### Expected output

```
==============================================================
  Agent Assembly — Agno Tool Policy Demo
==============================================================

Initializing Agent Assembly (gateway: http://localhost:8080, sdk-only mode)...
  Agent:    agno-demo-agent
  Gateway:  http://localhost:8080
  Mode:     sdk-only (offline demo)

Policy rules (local simulation of gateway policy):
  DENY   — execute_sql, run_shell_command  (arbitrary execution)
  ALLOW  — everything else

Agno governance hook installed on FunctionCall.execute.
Tools governed: get_weather, summarize_docs, execute_sql

Running governed tool calls:
--------------------------------------------
  → get_weather({'city': 'London'})
     ✅ ALLOWED  — Weather in London: sunny, 22C (mock)

  → summarize_docs({'topic': 'policy enforcement'})
     ✅ ALLOWED  — Summary for 'policy enforcement': Agent Assembly provides governance... (mock)

  → execute_sql({'sql': 'DROP TABLE users; --'})
     ❌ BLOCKED  — [BLOCKED by governance policy] Tool 'execute_sql' is blocked by policy rule 'deny_arbitrary_execution'.. Please choose a different approach to accomplish this task.

Assembly context shut down.
```

## Run the smoke tests

The example ships offline smoke tests that drive real Agno `@tool` functions through the real `AgnoPatch` and assert genuine governance — an allowed tool runs and returns its output, a denied tool's body is short-circuited before it runs (the negative control):

```bash
cd python/agno-tool-policy
uv sync --extra dev
uv run pytest tests/ -v
```

## Links

- [Example directory](https://github.com/ai-agent-assembly/agent-assembly-examples/tree/master/python/agno-tool-policy)
- [Example README](https://github.com/ai-agent-assembly/agent-assembly-examples/blob/master/python/agno-tool-policy/README.md)
- [Agno documentation](https://docs.agno.com/)
