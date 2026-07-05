# Examples

Runnable examples for the Agent Assembly Python SDK. Each example's status below tells you
whether it runs as-is or needs a reachable gateway.

| Example | Status | Notes |
| --- | --- | --- |
| [`type_checking/`](./type_checking/) | ✅ **Validated** | mypy-clean and runs offline — constructs the public typed models. See its [README](./type_checking/README.md). |
| [`basic_usage.py`](./basic_usage.py) | ⚠️ **Illustrative** | Shows the `init_assembly()` + `AgentConfig` shape. Calls `init_assembly()` against a gateway URL, so it needs a **reachable gateway** to run end to end. |

## Looking for a complete, offline example?

The canonical validated end-to-end example is the **LangChain ReAct quick start** in the
repository [README](../README.md#quick-start) — it runs fully offline against a mock LLM with no
gateway or API keys. The [Framework examples](https://docs.agent-assembly.com/python-sdk/latest/usage/framework-examples/)
guide lists every supported framework and which ones have a vendored runnable example yet.

## Running an example

```bash
uv sync                                   # set up the dev environment
uv run python examples/basic_usage.py     # (needs a reachable gateway)
uv run python examples/type_checking/type_checking_example.py
```
