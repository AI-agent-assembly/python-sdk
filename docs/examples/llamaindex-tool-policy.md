# LlamaIndex

Integrates Agent Assembly with [LlamaIndex](https://docs.llamaindex.ai/) using the **native `LlamaIndexAdapter`**, so every tool call a LlamaIndex agent makes is governed automatically — no per-tool wrapper.

## What this example demonstrates

- Initializing Agent Assembly with `init_assembly()` in offline `sdk-only` mode.
- Registering the native `LlamaIndexAdapter`, which patches the concrete `llama_index.core.tools.FunctionTool.call` / `acall` execution methods — the exact methods a `FunctionAgent` / `ReActAgent` invokes to run a tool.
- Running an **allowed** tool call (`query_index`) and another **allowed** call (`summarize_docs`) through the patched `FunctionTool.call`.
- Running a **denied** tool call (`execute_sql`, blocked by `deny_arbitrary_execution`) — its body never executes; the adapter returns a `ToolOutput` flagged `is_error=True` carrying a `[BLOCKED by governance policy]` message instead of raising, so the agent loop can react.
- A fully **offline** run — no API key, no running gateway, and no live LLM.

## The framework / library

[LlamaIndex](https://docs.llamaindex.ai/) is the agent framework governed in this example. The package is imported as `llama_index.core`, and the adapter advertises support for `>=0.10.0` via `get_supported_versions()`.

Version pins (from `pyproject.toml`):

| Dependency | Version |
|---|---|
| `llama-index-core` | `>=0.14.22` |
| `agent-assembly` | `>=0.0.1rc5` (the release that ships the LlamaIndex adapter) |
| Python | `>=3.12` |

## How it works

`init_assembly()` is opened as a context manager in offline `sdk-only` mode with the agent id `llamaindex-demo-agent`:

```python
with init_assembly(
    gateway_url=gateway_url,
    api_key=api_key,
    agent_id="llamaindex-demo-agent",
    mode="sdk-only",
) as ctx:
    ...
```

**The hook point.** LlamaIndex routes every tool invocation through a `BaseTool` subclass, but `BaseTool.call` / `acall` are *abstract* — the real bodies live on concrete classes such as `FunctionTool`. The adapter therefore patches the concrete `FunctionTool.call` (sync) and `acall` (async) methods directly:

```python
from agent_assembly.adapters.llamaindex import LlamaIndexAdapter

adapter = LlamaIndexAdapter()
adapter.register_hooks(interceptor)
# FunctionTool.call / acall are now governed.
...
adapter.unregister_hooks()  # restores the original methods
```

Because both methods are patched, the modern agent stack is covered either way: `FunctionAgent` / `ReActAgent` (via `AgentWorkflow`) `await tool.acall(...)`, while the legacy / sync path calls `tool.call(...)`.

**The `@dispatcher.span` descriptor nuance.** LlamaIndex wraps `call` / `acall` with an instrumentation decorator (`@dispatcher.span`), so `FunctionTool.call` yields a fresh bound wrapper on every attribute access. The adapter captures the stable original from the class `__dict__` (not the attribute) to restore on revert, and invokes the original through the descriptor protocol (`original_call.__get__(self, type(self))(...)`) so the instance binds correctly as `self` — a plain unbound call would lose `self`. This is handled inside the adapter; the example does not need to deal with it.

The adapter calls `interceptor.check_tool_start(...)` before a tool body runs. The example's `LocalPolicyEngine` (`src/policy.py`) is that interceptor: it returns a gateway-format `{"status": "allow"}` / `{"status": "deny", "reason": ...}` verdict, denying `execute_sql` and `run_shell_command` and allowing everything else. An unknown / malformed verdict denies rather than silently allowing.

**Deny is non-raising.** On a `deny`, the patch does not raise — it returns a `ToolOutput(is_error=True)` whose `content` carries the `[BLOCKED by governance policy]` message. The security-relevant invariant is that the tool's underlying function never executes; returning a well-formed error result lets an agent loop observe the block and choose another approach instead of crashing.

## Prerequisites & running it

See [Preparing the runtime environment](preparing-the-runtime-environment.md) for the shared prerequisites.

Then run the example (offline — no API key and no running gateway required):

```bash
cd python/llamaindex-tool-policy
uv sync --extra dev
uv run python src/main.py
```

### Expected output

```
==============================================================
  Agent Assembly — LlamaIndex Tool Policy Demo
==============================================================

Initializing Agent Assembly (gateway: http://localhost:8080, sdk-only mode)...
  Agent:    llamaindex-demo-agent
  Gateway:  http://localhost:8080
  Mode:     sdk-only (offline demo)

Policy rules (local simulation of gateway policy):
  DENY   — execute_sql, run_shell_command  (arbitrary execution)
  ALLOW  — everything else

Registering the native LlamaIndex governance adapter...
  FunctionTool.call / acall are now governed by Agent Assembly.

Running governed tool calls:
--------------------------------------------
  → query_index({'query': 'what is Agent Assembly?'})
     ✅ ALLOWED  — 📚 Index results for 'what is Agent Assembly?': ...

  → summarize_docs({'topic': 'policy enforcement'})
     ✅ ALLOWED  — 📝 Summary for 'policy enforcement': Agent Assembly provides governance...

  → execute_sql({'sql': 'DROP TABLE users; --'})
     ❌ BLOCKED  — [BLOCKED by governance policy] Tool 'execute_sql' is blocked by policy rule 'deny_arbitrary_execution'. ...
```

The two safe tools run and return their results; `execute_sql` is blocked before its body runs, surfacing the `[BLOCKED by governance policy]` message from the `ToolOutput` the adapter returns.

### Switching to production mode

In `sdk-only` mode the example reverts the auto-detected no-op patch and wires its own `LocalPolicyEngine` as the live interceptor. Against a real deployment you instead start an Agent Assembly gateway (or use your SaaS workspace URL), supply credentials via `.env`, and let `init_assembly()` auto-detect and register the LlamaIndex adapter against the live gateway interceptor — the tool-call code does not change; only the policy source does.

## Run the smoke tests

The example ships offline smoke tests that drive the **real** adapter — `LlamaIndexAdapter.register_hooks` patches `FunctionTool.call`, then an allowed tool runs and a denied tool's body never executes (the test asserts the tool function was never invoked and that the `[BLOCKED by governance policy]` marker is present). Each test reverts the patch so the global `FunctionTool` class is left clean.

```bash
uv run pytest tests/ -v
```

## Links

- [Example directory](https://github.com/ai-agent-assembly/examples/tree/master/python/llamaindex-tool-policy)
- [Example README](https://github.com/ai-agent-assembly/examples/blob/master/python/llamaindex-tool-policy/README.md)
- [LlamaIndex documentation](https://docs.llamaindex.ai/)
