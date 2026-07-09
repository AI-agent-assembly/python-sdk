# OpenAI Agents SDK

This example integrates Agent Assembly with the OpenAI Agents SDK to enforce governance policy — including approval gates — on tool calls before they execute.

## What this example demonstrates

- Initializing Agent Assembly with `init_assembly()`.
- Enforcing a governance policy using `AssemblyCallbackHandler` plus a policy interceptor.
- Running an **allowed** tool call (`search_documents`).
- Running a tool that requires **human approval** (`send_message_to_user` — auto-denied offline).
- Running a **denied** tool call (`delete_record` — blocked by a policy rule).
- How the `OpenAIAgentsPatch` intercepts `FunctionTool.__call__` at the framework level.

## The framework / library

This example is built on the [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/).

Version pins (from `pyproject.toml`):

| Dependency | Constraint |
|---|---|
| Python | `>=3.12` |
| `agent-assembly` | `>=0.0.1a2` |
| `openai-agents` | `>=0.0.3` |

Dev extras: `pytest>=8.0.0`, `pytest-mock>=3.14.0`, `pytest-asyncio>=0.23.0`.

## How it works

The demo runs entirely offline and walks three tool calls through the governance flow:

1. **`init_assembly()`** is called with `gateway_url`, `api_key`, `agent_id="openai-agents-demo"`, and `mode="sdk-only"`, yielding an assembly context (`ctx`). The gateway URL defaults to `http://localhost:8080` and the API key is read from the environment (both optional offline).
2. A **`LocalPolicyEngine`** (from `src/policy.py`) acts as the policy interceptor, simulating the rules the gateway would enforce in production. It exposes `check_tool_start()` returning `"allow"`, `"deny"`, or `"pending"`, and `wait_for_tool_approval()` for the approval gate.
3. An **`AssemblyCallbackHandler`** is constructed with that engine as its `interceptor`. Each demo call invokes `handler.on_tool_start(...)` before the tool function runs.
4. The policy outcome drives the result:
   - **allow** — the tool function runs and its return value is printed.
   - **deny** — `delete_record` / `drop_table` raise `ToolExecutionBlockedError` via policy rule `deny_destructive_data_ops`.
   - **pending** — `send_message_to_user` / `trigger_payment` require approval; offline there is no approver, so `wait_for_tool_approval()` denies them.

For real OpenAI Agents SDK usage, Agent Assembly's `OpenAIAgentsPatch` intercepts `FunctionTool.__call__` at the framework level automatically once `init_assembly()` has run.

## Prerequisites & running it

See [Preparing the runtime environment](preparing-the-runtime-environment.md) for the shared prerequisites.

Then, from the example directory:

```bash
cd python/openai-agents-sdk
uv sync --extra dev
uv run python src/main.py
```

No `OPENAI_API_KEY` is required for the offline demo.

## Code walkthrough

The three tools are plain Python functions, classified by intent (`src/tools.py`):

```python
def search_documents(query: str) -> str:
    """Search the internal knowledge base for the given query."""
    return f"📄 Search results for '{query}': [doc-42, doc-17, doc-99] (mock)"


def delete_record(record_id: str) -> str:
    """Permanently delete a database record."""
    return f"Record {record_id} deleted."
```

The local policy engine maps tool names to outcomes (`src/policy.py`):

```python
DENIED_TOOLS: frozenset[str] = frozenset({
    "delete_record",
    "drop_table",
})

APPROVAL_REQUIRED_TOOLS: frozenset[str] = frozenset({
    "send_message_to_user",
    "trigger_payment",
})
```

`main.py` wires the policy engine into the callback handler and runs each governed call:

```python
with init_assembly(
    gateway_url=gateway_url,
    api_key=api_key,
    agent_id="openai-agents-demo",
    mode="sdk-only",
) as ctx:
    policy = LocalPolicyEngine()
    handler = AssemblyCallbackHandler(interceptor=policy)
```

A blocked tool surfaces as `ToolExecutionBlockedError`, which the demo catches and prints:

```python
try:
    handler.on_tool_start(
        serialized={"name": tool_name, "type": "tool"},
        input_str=input_str,
        run_id=run_id,
    )
    fn = _TOOL_FNS[tool_name]
    result = fn(**json.loads(input_str))
    print(f"     ✅ ALLOWED  — {result}")
except ToolExecutionBlockedError as exc:
    print(f"     ❌ BLOCKED  — {exc}")
```

## Notes & caveats

!!! note "Offline mode"
    The demo runs in `sdk-only` mode and requires no `OPENAI_API_KEY` and no running gateway. The `LocalPolicyEngine` simulates gateway policy locally. Tools requiring approval are auto-denied offline because no approver is available.

!!! tip "Extending to a real agent"
    With an `OPENAI_API_KEY` set, you can extend `main.py` to create a real `openai.agents.Agent` with your `FunctionTool` instances. Agent Assembly's `OpenAIAgentsPatch` intercepts every tool call automatically once `init_assembly()` has run. To configure production mode, copy `.env.example` to `.env` and set `AGENT_ASSEMBLY_GATEWAY_URL`, `AGENT_ASSEMBLY_API_KEY`, and `OPENAI_API_KEY`.

!!! warning "Troubleshooting"
    | Problem | Fix |
    |---|---|
    | `ModuleNotFoundError: agent_assembly` | Run `uv sync` first |
    | `ModuleNotFoundError: openai` | Run `uv sync` — `openai-agents` is a required dependency |
    | `ToolExecutionBlockedError` in tests | Expected — the deny/approval policy rules are intentional |

## Expected behavior

```
==============================================================
  Agent Assembly — OpenAI Agents SDK Demo
==============================================================

Initializing Agent Assembly (gateway: http://localhost:8080, sdk-only mode)...
  Agent:    openai-agents-demo
  Gateway:  http://localhost:8080
  Mode:     sdk-only (offline demo)

Policy rules (local simulation of gateway policy):
  DENY      — delete_record, drop_table  (destructive data ops)
  APPROVAL  — send_message_to_user, trigger_payment
  ALLOW     — everything else

Running governed tool calls:
--------------------------------------------
  → search_documents({"query": "agent governance best practices"})
     ✅ ALLOWED  — 📄 Search results for 'agent governance best practices': ...

  → send_message_to_user({"user_id": "u-001", "message": "Your report is ready."})
     ❌ BLOCKED  — Tool 'send_message_to_user' requires approval, but no approver is available in offline mode.

  → delete_record({"record_id": "rec-7829"})
     ❌ BLOCKED  — Tool 'delete_record' is permanently blocked by policy rule 'deny_destructive_data_ops'.
```

## Links

- [Example directory](https://github.com/ai-agent-assembly/examples/tree/master/python/openai-agents-sdk)
- [Example README](https://github.com/ai-agent-assembly/examples/blob/master/python/openai-agents-sdk/README.md)
- [OpenAI Agents SDK docs](https://openai.github.io/openai-agents-python/)
