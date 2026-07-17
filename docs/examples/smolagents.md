# Smolagents

Integrates Agent Assembly with [Smolagents](https://github.com/huggingface/smolagents) (Hugging Face) to enforce governance policy on tool calls before they execute.

## What this example demonstrates

- Initializing Agent Assembly with `init_assembly()` in offline `sdk-only` mode.
- Governing **real** `smolagents.Tool` instances — `SmolagentsAdapter` patches `smolagents.tools.Tool.__call__`, the single chokepoint every smolagents tool execution flows through (`Tool.__call__` runs `self.forward(...)`).
- Running an **allowed** tool call (`search_docs`, `summarize`) that executes its real body, and a **denied** tool call (`run_shell_command`) that is short-circuited with the `[BLOCKED by governance policy]` message **before** `forward()` runs.
- How a denied tool's `forward()` body genuinely never executes — proven by a negative-control smoke test that runs the same tool ungoverned and watches it execute.
- A fully **offline** run: no running gateway, no model, and no API credentials.

## The framework / library

[Smolagents](https://github.com/huggingface/smolagents) (Hugging Face) is the agent framework governed in this example. Every smolagents tool — whether driven by a `ToolCallingAgent` or a `CodeAgent` — executes through `Tool.__call__`, so a single hook governs both agent styles.

Version pins (from `pyproject.toml`):

| Dependency | Version |
|---|---|
| `smolagents` | `>=1.0.0,<2.0.0` |
| `agent-assembly` | `>=0.0.1rc6` (the release that ships the Smolagents adapter) |
| Python | `>=3.12` |

## How it works

`init_assembly()` is opened as a context manager in offline `sdk-only` mode with the agent id `smolagents-demo-agent`:

```python
with init_assembly(
    gateway_url=gateway_url,
    api_key=api_key,
    agent_id="smolagents-demo-agent",
    mode="sdk-only",
) as ctx:
    ...
```

**The hook point.** The Smolagents adapter patches `smolagents.tools.Tool.__call__` — the single tool-execution chokepoint in the 1.x line. Both agent styles reach it: the `ToolCallingAgent` path (`MultiStepAgent.execute_tool_call` resolves the tool and calls `tool(...)`) and the `CodeAgent` path (tools are injected into the sandbox namespace and invoked as plain callables, which dispatches to `Tool.__call__`). Because `__call__` runs `self.forward(*args, **kwargs)` to execute the tool body, wrapping it lets governance observe the tool name and arguments and decide **before** the body runs.

When the policy returns a `deny` verdict, the wrapper returns the `[BLOCKED by governance policy]` message **instead of** calling `forward()`, so the denied tool body never executes (fail-closed under `enforce`). On `allow`, the real `forward()` runs and its result is recorded.

**Offline note.** A smolagents agent (`ToolCallingAgent` / `CodeAgent`) drives its loop against an **LLM** that *decides* which tool to call, which needs a model and a network call. To keep the example runnable with no secrets, it does not start a live model. Instead it invokes the real governed `smolagents.Tool` instances directly — the exact call (`tool(**inputs)` → `Tool.__call__` → `forward`) a smolagents agent makes to execute a tool. The genuine allow / deny governance code runs; only the LLM that would *choose* the tools is absent. The tools are real `smolagents.Tool` subclasses and the governance is the production `SmolagentsPatch` — this is not a mock.

**Wiring note.** `init_assembly()` auto-detects smolagents and installs the hook with its default interceptor. So that the **offline policy** wins, the example applies the adapter's patch with a `LocalPolicyEngine` **before** calling `init_assembly()` (the patch is idempotent, so init's auto-detect then leaves the already-governed `Tool.__call__` alone). In production you skip this — `init_assembly()` wires the real gateway-backed interceptor for you.

```python
policy = LocalPolicyEngine()
patch = SmolagentsPatch(policy)
patch.apply()
```

The offline `LocalPolicyEngine` returns decisions in the gateway wire format (`src/policy.py`). It denies the destructive tools and allows everything else.

## Prerequisites & running it

See [Preparing the runtime environment](preparing-the-runtime-environment.md) for the shared prerequisites.

Then run the example (offline — no model/API credentials and no running gateway required):

```bash
cd python/smolagents-tool-policy
uv sync --extra dev
uv run python src/main.py
```

### Expected output

```
==============================================================
  Agent Assembly — Smolagents Tool Policy Demo
==============================================================

Initializing Agent Assembly (gateway: http://localhost:8080, sdk-only mode)...
  Agent:    smolagents-demo-agent
  Gateway:  http://localhost:8080
  Mode:     sdk-only (offline demo)

Policy rules (local simulation of gateway policy):
  DENY   — run_shell_command, delete_records  (destructive ops)
  ALLOW  — everything else

Governing real smolagents.Tool instances via Tool.__call__:
  Tools: search_docs, summarize, run_shell_command

Running governed tool calls:
--------------------------------------------
  → search_docs({'query': 'what is Agent Assembly?'})
     ✅ ALLOWED  — docs results for 'what is Agent Assembly?': [chunk-12, chunk-44, chunk-07] (mock)

  → summarize({'topic': 'policy enforcement'})
     ✅ ALLOWED  — summary of 'policy enforcement': Agent Assembly governs agent tool calls... (mock)

  → run_shell_command({'command': 'rm -rf /var/data'})
     ❌ BLOCKED  — [BLOCKED by governance policy] Tool 'run_shell_command' is blocked by policy rule 'deny_destructive_operations'.

Assembly context shut down.
```

The two safe tools (`search_docs`, `summarize`) run their real bodies; the destructive `run_shell_command` is short-circuited by policy before its `forward()` executes.

## Run the smoke tests

The example ships an offline smoke suite that exercises the real adapter governing real `smolagents.Tool` instances:

```bash
cd python/smolagents-tool-policy
uv run pytest tests/ -v
```

It asserts that an allowed tool runs its body, a denied tool returns the `[BLOCKED by governance policy]` marker (and `forward()` never executes), and that a negative-control case running the same tool with **no adapter applied** executes destructively — proving the governed cases are real interception, not a no-op.

## Links

- [Example directory](https://github.com/ai-agent-assembly/examples/tree/master/python/smolagents-tool-policy)
- [Example README](https://github.com/ai-agent-assembly/examples/blob/master/python/smolagents-tool-policy/README.md)
- [Smolagents documentation](https://github.com/huggingface/smolagents)
