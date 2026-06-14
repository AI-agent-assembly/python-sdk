# Custom tool policy (no framework)

The simplest Agent Assembly integration — wrap plain Python functions with governance, no AI framework required.

## What this example demonstrates

This example shows how to add Agent Assembly governance to plain Python functions using the minimal `governed()` wrapper helper. It covers:

- Initializing Agent Assembly with `init_assembly()`.
- Wrapping any Python function with governance using `governed()`.
- Two **allowed** tool calls (`compute_sum`, `fetch_stock_price`).
- Two **denied** tool calls (`send_http_request`, `write_to_disk` — blocked by policy).
- That the wrapped function body **never executes** when governance denies it.
- The `governed()` pattern as the building block for the `GovernedToolRunner` shown in the [LlamaIndex — manual tool policy](llamaindex-tool-policy.md) example.

## The framework / library

There is **no AI framework** in this example — it depends only on `agent-assembly`, plus pure Python. From `pyproject.toml`:

```toml
dependencies = [
    "agent-assembly>=0.0.1a2",
]
```

No LangChain, LlamaIndex, or any agent framework is involved; the tools are ordinary Python callables.

## How it works

1. `init_assembly()` opens an Assembly context in `sdk-only` mode (offline demo — no gateway or API key needed).
2. `governed(tool_name, fn, policy)` wraps a plain callable, returning a new callable.
3. When the wrapped callable is invoked, the policy check runs **before** the function body via the `AssemblyCallbackHandler`'s `on_tool_start`.
4. If the policy denies the tool, `ToolExecutionBlockedError` surfaces and the original function (`fn`) is **never called**.

In `main.py`, the four tools from `tools.py` are wrapped, then driven through a demo loop. Allowed calls return their result; denied calls raise `ToolExecutionBlockedError`, which the loop catches and reports as blocked.

## Prerequisites & running it

See [Preparing the runtime environment](preparing-the-runtime-environment.md) for the shared prerequisites.

Then, from the example directory:

```bash
cd python/custom-tool-policy
uv sync --extra dev
uv run python src/main.py
```

No API key, no gateway, and no AI framework are required.

## Code walkthrough

The `governed()` helper from `policy.py` — it wraps a callable so the policy check runs before the function body:

```python
def governed(tool_name: str, fn: Any, policy: LocalPolicyEngine) -> Any:
    handler = AssemblyCallbackHandler(interceptor=policy)

    def _wrapper(**kwargs: Any) -> Any:
        import json

        handler.on_tool_start(
            serialized={"name": tool_name, "type": "tool"},
            input_str=json.dumps(kwargs),
            run_id=uuid4(),
        )
        return fn(**kwargs)

    _wrapper.__name__ = tool_name
    return _wrapper
```

A plain tool function from `tools.py` — no framework, just a regular callable:

```python
def fetch_stock_price(ticker: str) -> str:
    """Return the current stock price for a ticker symbol."""
    prices = {"AAPL": 211.30, "GOOG": 178.52, "MSFT": 430.00}
    price = prices.get(ticker.upper(), 42.00)
    return f"${price:.2f} (mock)"
```

The demo loop from `main.py` — allowed calls return a result, denied calls raise:

```python
for tool_name, kwargs in _DEMO_CALLS:
    print(f"  → {tool_name}({kwargs})")
    try:
        result = tools[tool_name](**kwargs)
        print(f"     ✅ ALLOWED  — {result}")
    except ToolExecutionBlockedError as exc:
        print(f"     ❌ BLOCKED  — {exc}")
    print()
```

## Notes & caveats

!!! note
    `governed()` is the minimal building block. The wrapped function body **never runs** when the policy denies the tool — the `ToolExecutionBlockedError` is raised inside the wrapper before `fn(**kwargs)` is reached.

!!! tip
    This same `governed()` pattern is the foundation for the `GovernedToolRunner` shown in the [LlamaIndex — manual tool policy](llamaindex-tool-policy.md) example.

Troubleshooting (from the README):

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: agent_assembly` | Run `uv sync` first |
| `ToolExecutionBlockedError` in tests | Expected — the deny rules for `send_http_request` and `write_to_disk` are intentional |

The gateway URL defaults to `http://localhost:8080` and can be overridden via the `AGENT_ASSEMBLY_GATEWAY_URL` environment variable; `AGENT_ASSEMBLY_API_KEY` is read but not required in this offline demo.

## Expected behavior

```
==============================================================
  Agent Assembly — Custom Tool Policy Demo
  (no AI framework required)
==============================================================

Initializing Agent Assembly (gateway: http://localhost:8080, sdk-only mode)...
  Agent:    custom-tool-demo-agent
  Gateway:  http://localhost:8080
  Mode:     sdk-only (offline demo)

Policy rules (local simulation of gateway policy):
  DENY   — send_http_request, write_to_disk  (network / disk writes)
  ALLOW  — everything else

Running governed tool calls:
--------------------------------------------
  → compute_sum({'a': 12.5, 'b': 7.3})
     ✅ ALLOWED  — 19.8

  → fetch_stock_price({'ticker': 'AAPL'})
     ✅ ALLOWED  — $211.30 (mock)

  → send_http_request({'url': 'https://example.com/data', 'method': 'POST'})
     ❌ BLOCKED  — Tool 'send_http_request' is blocked by policy rule 'deny_network_and_disk_writes'.

  → write_to_disk({'path': '/etc/cron.d/evil', 'content': 'rm -rf /'})
     ❌ BLOCKED  — Tool 'write_to_disk' is blocked by policy rule 'deny_network_and_disk_writes'.
```

## Links

- [Example directory](https://github.com/ai-agent-assembly/agent-assembly-examples/tree/master/python/custom-tool-policy)
- [README](https://github.com/ai-agent-assembly/agent-assembly-examples/blob/master/python/custom-tool-policy/README.md)
- [LlamaIndex — manual tool policy](llamaindex-tool-policy.md)
