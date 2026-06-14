# LlamaIndex — manual tool policy

Add Agent Assembly governance to [LlamaIndex](https://docs.llamaindex.ai/) tool calls by wrapping each `FunctionTool` with a `GovernedToolRunner`, since LlamaIndex has no native adapter yet.

## What this example demonstrates

Because LlamaIndex does not yet have a native Agent Assembly adapter, this example shows the **manual wrapper pattern**: each `FunctionTool` is wrapped with `GovernedToolRunner` so governance runs before every tool invocation. This pattern works for any Python callable.

It walks through:

- Initializing Agent Assembly with `init_assembly()`.
- Applying governance to `FunctionTool` calls using `GovernedToolRunner`.
- Running an **allowed** tool call (`query_index`).
- Running another **allowed** tool call (`summarize_docs`).
- Running a **denied** tool call (`execute_sql` — blocked by `deny_arbitrary_execution`).
- How to add governance to any framework that lacks a native adapter.

## The framework / library

[LlamaIndex](https://docs.llamaindex.ai/) — the example depends on `llama-index-core>=0.10.0` for its `FunctionTool` abstraction, and on the Agent Assembly Python SDK pinned at `agent-assembly>=0.0.1a2` (per `pyproject.toml`). Python `>=3.12` is required.

## How it works

`main.py` opens an Agent Assembly context with `init_assembly()`, passing `agent_id="llamaindex-demo-agent"` and `mode="sdk-only"` so the demo runs offline:

```python
with init_assembly(
    gateway_url=gateway_url,
    api_key=api_key,
    agent_id="llamaindex-demo-agent",
    mode="sdk-only",
) as ctx:
    ...
```

The `gateway_url` defaults to `http://localhost:8080` (read from `AGENT_ASSEMBLY_GATEWAY_URL`), and `api_key` comes from `AGENT_ASSEMBLY_API_KEY`. Neither is required for the offline demo.

Each tool is then wrapped in a `GovernedToolRunner`, which holds the callable plus an `AssemblyCallbackHandler` configured with a `LocalPolicyEngine`. Calling `runner.run(**kwargs)` first fires `on_tool_start`, which routes through the policy engine before the underlying function executes. When the policy denies a tool (here, `execute_sql` and `run_shell_command`), the call surfaces as a `ToolExecutionBlockedError`, which `main.py` catches and prints as `❌ BLOCKED`.

Unlike the native-adapter examples — where `init_assembly()` wires governance into the framework automatically — this is the fallback path for frameworks that lack a native adapter: you place the `GovernedToolRunner` in front of each callable yourself. As `main.py` notes, once a native LlamaIndex adapter exists, `GovernedToolRunner` will no longer be needed.

## Prerequisites & running it

See [Preparing the runtime environment](preparing-the-runtime-environment.md) for the shared prerequisites.

Then:

```bash
cd python/llamaindex-tool-policy
uv sync --extra dev
uv run python src/main.py
```

The demo runs fully offline — no API key and no running gateway are required.

## Code walkthrough

`policy.py` defines the local policy engine and the runner that bridges any callable into governance. The denied tools are a static set, and `check_tool_start` returns an allow/deny verdict:

```python
DENIED_TOOLS: frozenset[str] = frozenset({
    "execute_sql",
    "run_shell_command",
})


class LocalPolicyEngine:
    """Simulates Agent Assembly gateway policy enforcement in offline mode."""

    def check_tool_start(self, serialized, input_str, run_id=None, **kwargs):
        tool_name = serialized.get("name", "")
        if tool_name in DENIED_TOOLS:
            return {
                "status": "deny",
                "reason": (
                    f"Tool '{tool_name}' is blocked by policy rule "
                    "'deny_arbitrary_execution'."
                ),
            }
        return {"status": "allow"}
```

`GovernedToolRunner.run()` serializes the kwargs, calls the handler's `on_tool_start` to enforce policy, then invokes the wrapped function:

```python
def run(self, **kwargs: Any) -> Any:
    import json

    input_str = json.dumps(kwargs)
    self._handler.on_tool_start(
        serialized={"name": self._tool_name, "type": "tool"},
        input_str=input_str,
        run_id=uuid4(),
    )
    return self._fn(**kwargs)
```

`tools.py` defines the three LlamaIndex `FunctionTool`s used by the demo:

```python
query_index = FunctionTool.from_defaults(
    fn=_query_index_fn,
    name="query_index",
    description="Query the document index for relevant information.",
)
```

`main.py` builds a runner per tool and executes the demo calls:

```python
runners = {
    name: GovernedToolRunner(name, fn, policy)
    for name, fn, _ in _DEMO_CALLS
}
```

## Notes & caveats

!!! note "Manual pattern for frameworks without a native adapter"
    LlamaIndex does not yet have a native Agent Assembly adapter, so governance is applied explicitly via `GovernedToolRunner`. When a native adapter becomes available, `init_assembly()` will apply governance automatically and the manual runner will no longer be needed.

Troubleshooting (from the README):

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: agent_assembly` | Run `uv sync` first |
| `ModuleNotFoundError: llama_index` | Run `uv sync` — `llama-index-core` is a required dependency |
| `ToolExecutionBlockedError` in tests | Expected — the deny policy rule for `execute_sql` is intentional |

## Expected behavior

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

Wrapping LlamaIndex tools with GovernedToolRunner...
  Tools wrapped: query_index, summarize_docs, execute_sql

Running governed tool calls:
--------------------------------------------
  → query_index({'query': 'what is Agent Assembly?'})
     ✅ ALLOWED  — 📚 Index results for 'what is Agent Assembly?': ...

  → summarize_docs({'topic': 'policy enforcement'})
     ✅ ALLOWED  — 📝 Summary for 'policy enforcement': Agent Assembly provides governance...

  → execute_sql({'sql': 'DROP TABLE users; --'})
     ❌ BLOCKED  — Tool 'execute_sql' is blocked by policy rule 'deny_arbitrary_execution'.
```

## Links

- [Example directory](https://github.com/ai-agent-assembly/agent-assembly-examples/tree/master/python/llamaindex-tool-policy)
- [Example README](https://github.com/ai-agent-assembly/agent-assembly-examples/blob/master/python/llamaindex-tool-policy/README.md)
- [LlamaIndex docs](https://docs.llamaindex.ai/)
