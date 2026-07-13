# Haystack

Integrates Agent Assembly with [Haystack](https://haystack.deepset.ai/) (deepset) to enforce governance policy on a real Haystack agent's tool calls before they execute, using the SDK's native Haystack adapter.

## What this example demonstrates

- Initializing Agent Assembly with `init_assembly()` in offline `sdk-only` mode (which also auto-detects Haystack).
- Installing the native Haystack adapter — `HaystackPatch` patches `haystack.tools.Tool.invoke`, the single tool-execution chokepoint Haystack 2.x uses.
- Running real `haystack.tools.Tool` instances through a genuine `ToolInvoker` (the component a Haystack `Agent` uses to run a model-chosen tool call).
- An **allowed** tool call (`query_index`) and another **allowed** tool call (`summarize_docs`) — their tool bodies execute.
- A **denied** tool call (`execute_sql`, blocked by `deny_arbitrary_execution`) — the deny short-circuits `Tool.invoke` and returns a `[BLOCKED by governance policy]` result *before the tool body runs*.
- No LLM, API key, or running gateway is involved — the tools are driven offline through a hand-built `ToolCall`.

## The framework / library

[Haystack](https://haystack.deepset.ai/) (deepset; installed as `haystack-ai`, imported as `haystack`) is the agent framework governed in this example. Haystack 2.x is the line that exposes the agentic `Agent` / `ToolInvoker` tool-call path and the `haystack.tools.Tool.invoke` hook point the adapter patches; the 1.x line predates that API and is out of scope.

Version pins (from `pyproject.toml`):

| Dependency | Version |
|---|---|
| `haystack-ai` | `>=2.0.0,<3.0` |
| `agent-assembly` | `>=0.0.1rc4` (the release that ships the Haystack adapter) |
| Python | `>=3.12` |

## How it works

`init_assembly()` is opened as a context manager in offline `sdk-only` mode with the agent id `haystack-demo-agent`:

```python
with init_assembly(
    gateway_url=gateway_url,
    api_key=api_key,
    agent_id="haystack-demo-agent",
    mode="sdk-only",
) as ctx:
    ...
```

**The hook point.** The native adapter patches `haystack.tools.Tool.invoke`. That single method is the execution chokepoint Haystack 2.x routes *every* tool through: it governs both the bare `Tool.invoke()` path and the full agent loop, because `haystack.components.agents.Agent` dispatches its tool calls via `haystack.components.tools.ToolInvoker`, which itself calls `tool_to_invoke.invoke(**final_args)`. Patching `Tool.invoke` therefore intercepts every tool execution — which is why governance is wired there and not at the higher-level `Agent` / `ToolInvoker` layer. `HaystackAdapter.get_supported_versions()` returns `[">=2.0.0,<3.0"]`.

**Offline note.** No LLM is needed. The example builds three real `haystack.tools.Tool` instances (`src/tools.py`) and drives them through a genuine `ToolInvoker` fed a hand-built `ToolCall` — the exact shape a chat model would emit — so the governed `Tool.invoke` is exercised on the real agent tool-dispatch path with no model, credentials, or gateway in the loop.

**How deny short-circuits.** The patched `Tool.invoke` first calls the interceptor's `check_tool_start` hook. The offline `LocalPolicyEngine` (`src/policy.py`) returns a gateway-format decision dict — `{"status": "deny", "reason": ...}` for the arbitrary-execution tools, `{"status": "allow"}` otherwise. On a deny the adapter returns a `[BLOCKED by governance policy]` message *without calling the original `invoke`*, so the tool's underlying function never runs. The policy carries `_enforce = True`, putting the adapter in the fail-closed `enforce` posture (an unknown or malformed verdict denies rather than silently allowing).

In offline `sdk-only` mode `init_assembly()` wires a no-op interceptor (there is no live gateway to answer policy), so the example reverts that and re-installs the same native adapter against the `LocalPolicyEngine` to make a real allow/deny visible without a gateway:

```python
HaystackPatch(LocalPolicyEngine()).revert()  # drop the auto-applied no-op patch
patch = HaystackPatch(LocalPolicyEngine())
installed = patch.apply()
```

In production you instead point `init_assembly()` at a gateway and let its auto-detected adapter enforce real policy — no manual re-install is needed.

## Prerequisites & running it

See [Preparing the runtime environment](preparing-the-runtime-environment.md) for the shared prerequisites.

Then run the example (offline — no API key and no running gateway required):

```bash
cd python/haystack-tool-policy
uv sync --extra dev
uv run python src/main.py
```

### Expected output

The two safe tools run and the destructive tool is blocked before its body executes:

```
==============================================================
  Agent Assembly — Haystack Tool Policy Demo
==============================================================

Initializing Agent Assembly (gateway: http://localhost:8080, sdk-only mode)...
  Agent:    haystack-demo-agent
  Gateway:  http://localhost:8080
  Mode:     sdk-only (offline demo)

Policy rules (local simulation of gateway policy):
  DENY   — execute_sql, run_shell_command  (arbitrary execution)
  ALLOW  — everything else

Installing the native Haystack adapter against the demo policy...
  Adapter installed: True

Running real Haystack tools through a ToolInvoker:
--------------------------------------------
  → query_index({'query': 'what is Agent Assembly?'})
     ✅ ALLOWED  — Index results for 'what is Agent Assembly?': [chunk-12, chunk-44, chunk-07] (mock)

  → summarize_docs({'topic': 'policy enforcement'})
     ✅ ALLOWED  — Summary for 'policy enforcement': Agent Assembly provides governance... (mock)

  → execute_sql({'sql': 'DROP TABLE users; --'})
     ❌ BLOCKED  — [BLOCKED by governance policy] Tool 'execute_sql' is blocked by policy rule 'deny_arbitrary_execution'...

Tool bodies that actually executed: ['query_index', 'summarize_docs']
```

`execute_sql` is absent from the executed list — the deny short-circuited it before the tool ran, proving real governance rather than a no-op.

## Run the smoke tests

The example ships offline smoke tests that assert an allowed tool runs and a denied tool's body never executes:

```bash
uv run pytest tests/ -v
```

## Links

- [Example directory](https://github.com/ai-agent-assembly/examples/tree/master/python/haystack-tool-policy)
- [Example README](https://github.com/ai-agent-assembly/examples/blob/master/python/haystack-tool-policy/README.md)
- [Haystack documentation](https://haystack.deepset.ai/)
