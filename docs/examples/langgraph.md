# LangGraph — node-level governance

Enforce Agent Assembly policy on the tools a LangGraph graph's nodes call — before any tool executes — by wrapping a compiled `StateGraph` with node-level governance hooks.

## What this example demonstrates

- Initializing Agent Assembly with `init_assembly()` in offline `sdk-only` mode.
- Installing **node-level** governance hooks with `LangGraphAdapter`, which wraps a compiled `StateGraph`'s nodes.
- Routing tool calls through LangChain's `AssemblyCallbackHandler` so each tool is checked against policy.
- A linear graph `START → research → report → END` where:
  - `research` calls an **allowed** tool (`get_weather`).
  - `report` calls a **denied** tool (`delete_files` — blocked by policy).
- How `ToolExecutionBlockedError` halts the graph the moment a blocked tool is reached.

## The framework / library

[LangGraph](https://langchain-ai.github.io/langgraph/) builds stateful, graph-structured agent workflows. This example pins the following versions (from `pyproject.toml`):

| Dependency | Version |
|---|---|
| `agent-assembly` | `>= 0.0.1a2` |
| `langgraph` | `>= 0.2.0` |
| `langchain-core` | `>= 0.2.0` |
| Python | `>= 3.12` |

Dev extras (`--extra dev`): `pytest>=8.0.0`, `pytest-mock>=3.14.0`.

## How it works

`main.py` opens an Agent Assembly context with `init_assembly()` in `sdk-only` mode — fully offline, no gateway or LLM required:

```python
with init_assembly(
    gateway_url=gateway_url,
    api_key=api_key,
    agent_id="langgraph-demo-agent",
    mode="sdk-only",
) as ctx:
    ...
```

The gateway URL defaults to `http://localhost:8080`, read from `AGENT_ASSEMBLY_GATEWAY_URL`; `AGENT_ASSEMBLY_API_KEY` supplies the optional API key. Both are unset in the offline demo.

Inside the context, a `LocalPolicyEngine` (offline stand-in for gateway-side policy) is wired to an `AssemblyCallbackHandler`, and a `LangGraphAdapter` installs the node-level hooks:

```python
policy = LocalPolicyEngine()
handler = AssemblyCallbackHandler(interceptor=policy)

adapter = LangGraphAdapter()
adapter.set_process_agent_id(ctx.client.agent_id)
adapter.register_hooks(handler)
```

The adapter wraps the compiled graph's nodes so tool calls inside each node are governed. When the graph is invoked, each node calls a tool through the handler. `LocalPolicyEngine.check_tool_start` returns an allow / deny / pending decision; the handler raises `ToolExecutionBlockedError` for deny (and unresolved-pending) outcomes. The `research` node's `get_weather` is allowed, but the `report` node's `delete_files` is denied — so the graph halts mid-execution at the `report` node.

## Prerequisites & running it

See [Preparing the runtime environment](preparing-the-runtime-environment.md) for the shared prerequisites.

Then:

```bash
cd python/langgraph
uv sync --extra dev
uv run python src/main.py
```

The example runs **fully offline**: the graph is driven with deterministic nodes, so no LLM, API key, or running gateway is required.

## Code walkthrough

The graph is a linear two-node `StateGraph`, compiled and returned (`graph.py`):

```python
def build_graph(handler: AssemblyCallbackHandler) -> object:
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(GraphState)
    graph.add_node("research", lambda state: _research_node(handler, state))
    graph.add_node("report", lambda state: _report_node(handler, state))
    graph.add_edge(START, "research")
    graph.add_edge("research", "report")
    graph.add_edge("report", END)
    return graph.compile()
```

Each node fires a tool call through the handler. The `report` node calls the denied `delete_files` tool (`graph.py`):

```python
def _report_node(handler: AssemblyCallbackHandler, state: GraphState) -> GraphState:
    """Destructive node: calls the denied ``delete_files`` tool."""
    handler.on_tool_start(
        serialized={"name": "delete_files"},
        input_str='{"path": "/etc/passwd"}',
        run_id=uuid4(),
    )
    return {**state, "output": "deleted (should not be reached)"}
```

The local policy engine returns the deny decision the handler acts on (`policy.py`):

```python
def check_tool_start(self, serialized, input_str, run_id=None, **kwargs):
    tool_name = serialized.get("name", "")
    if tool_name in DENIED_TOOLS:
        return {
            "status": "deny",
            "reason": (
                f"Tool '{tool_name}' is blocked by policy rule "
                "'deny_destructive_operations'."
            ),
        }
    if tool_name in PENDING_TOOLS:
        return {
            "status": "pending",
            "reason": f"Tool '{tool_name}' requires human approval before execution.",
        }
    return {"status": "allow"}
```

`DENIED_TOOLS` is `{"delete_files", "write_file"}` and `PENDING_TOOLS` is `{"send_email"}`; everything else is allowed.

## Notes & caveats

!!! note
    The example runs fully offline. The graph is driven with deterministic nodes, so no LLM, API key, or running gateway is required, and no Agent Assembly gateway is needed for the demo. In offline mode, `wait_for_tool_approval` denies pending tools because no approver is available.

!!! tip
    Troubleshooting (from the README):

    - `ModuleNotFoundError: agent_assembly` → run `uv sync` first.
    - `ModuleNotFoundError: langgraph` → run `uv sync` — `langgraph` is a required dependency.
    - `ToolExecutionBlockedError` in tests → expected; the deny/pending policy rules are intentional.

!!! note "Switching to production mode"
    Start an Agent Assembly gateway (or use your SaaS workspace URL), copy `.env.example` to `.env`, and run with `AGENT_ASSEMBLY_GATEWAY_URL` / `AGENT_ASSEMBLY_API_KEY` set. In production, `init_assembly()` auto-detects LangGraph and registers the adapter automatically, the gateway enforces the policy rules, and `LocalPolicyEngine` is replaced with the gateway-backed interceptor.

## Expected behavior

```
==============================================================
  Agent Assembly — LangGraph Governed Agent Demo
==============================================================

Initializing Agent Assembly (gateway: http://localhost:8080, sdk-only mode)...
  Agent:    langgraph-demo-agent
  Gateway:  http://localhost:8080
  Mode:     sdk-only (offline demo)

Policy rules (local simulation of gateway policy):
  DENY    — delete_files, write_file  (destructive operations)
  PENDING — send_email                (requires human approval)
  ALLOW   — everything else

Invoking governed graph: START → research → report → END
--------------------------------------------
  → research node: get_weather
     ✅ ALLOWED  — gathered notes (mock response)
  → report node: delete_files
     ❌ BLOCKED  — Tool 'delete_files' is blocked by policy rule 'deny_destructive_operations'.

Assembly context shut down.
```

## Links

- [Example directory](https://github.com/ai-agent-assembly/agent-assembly-examples/tree/master/python/langgraph)
- [README](https://github.com/ai-agent-assembly/agent-assembly-examples/blob/master/python/langgraph/README.md)
- [LangGraph documentation](https://langchain-ai.github.io/langgraph/)
