# Framework compatibility

**In plain terms:** this page answers *which AI-agent frameworks does the Python SDK
govern, and at what versions?* — so you can confirm compatibility *before* you
integrate, rather than discovering an unsupported framework version at runtime.

Agent Assembly governs third-party agent frameworks without those frameworks needing to
be aware of it. You call `init_assembly()` once and the SDK detects which supported
frameworks are importable in your process and installs governance hooks for each (see
[Framework support](../examples/framework-support.md) for the adapter ↔ example status,
and [Core Concepts](../concepts/index.md#the-adapter-pattern) for the adapter pattern).

## Authoritative for Python — and where the cross-SDK index lives

**This page is the authoritative framework-compatibility reference for the Python SDK.**
The Python adapters under `agent_assembly/adapters/` and the ranges each one advertises
via `FrameworkAdapter.get_supported_versions()` are the source of truth — so the Python
table below is what to trust for Python, not a mirror of some other page.

The core docs host a **cross-SDK index/hub** that links out to each language SDK's own
compatibility page (this one for Python, plus the Node and Go equivalents). It is an
index, not the canonical matrix — each SDK's page is authoritative for its own language,
because the adapters live in the SDK:

- **[Cross-SDK framework-compatibility index →](https://docs.agent-assembly.com/core/stable/reference/framework-compatibility.html)**

!!! note "The `/stable/` link 404s until GA"
    That URL points at the `stable` documentation channel, which only activates at the
    first general-availability (`vX.Y.0`) release. Until then it returns *404 Not Found*
    by design — the same convention the other compatibility links follow. The Python
    table below is authoritative for the Python SDK regardless.

## Supported frameworks (Python SDK)

The Python SDK ships an adapter for each framework below under
`agent_assembly/adapters/`. The **Supported range** column is the constraint the adapter
itself advertises (`FrameworkAdapter.get_supported_versions()`); the **Tested version**
column is the exact release exercised by the live smoke suite (AAASM-3525) and the
`importorskip`-guarded integration tests. Where a framework's adapter accepts a broad
`>=` range but only one line is exercised in CI, the **Tested version** is the honest
statement of what is actually validated — older releases within the range are expected
to work but are not continuously tested.

| Framework | Import name | Adapter | Supported range | Tested version |
| --- | --- | --- | --- | --- |
| LangChain | `langchain` | `agent_assembly.adapters.langchain` | `>=0.1.0` | `0.3.x` line |
| LangGraph | `langgraph` | `agent_assembly.adapters.langgraph` | `>=0.1.0` | `0.2.x` line |
| Pydantic AI | `pydantic_ai` | `agent_assembly.adapters.pydantic_ai` | `>=0.1.0` (both the `<0.3` `Tool._run` and `>=0.3` `AbstractToolset.call_tool` hook points) | `>=0.3.0` — see [note below](#pydantic-ai-version-range) |
| CrewAI | `crewai` | `agent_assembly.adapters.crewai` | `>=0.1.0` | `1.14.x` |
| Google ADK | `google.adk` | `agent_assembly.adapters.google_adk` | `>=1.0.0,<2.0` | `1.x` line |
| Haystack | `haystack` | `agent_assembly.adapters.haystack` | `>=2.0.0,<3.0` (the Haystack 2.x `Tool.invoke` hook point, used by both `Tool.invoke()` and the `Agent`/`ToolInvoker` tool-call loop) | `2.30.x` |
| LlamaIndex | `llama_index.core` | `agent_assembly.adapters.llamaindex` | `>=0.10.0` | `0.14.x` |
| MCP | `mcp` | `agent_assembly.adapters.mcp` | `>=1.0.0` | `1.27.x` |
| OpenAI Agents | `agents` | `agent_assembly.adapters.openai_agents` | `>=0.1.0` | `0.17.x` |
| Smolagents | `smolagents` | `agent_assembly.adapters.smolagents` | `>=1.0.0,<2.0.0` | `1.26.x` |
| Agno | `agno` | `agent_assembly.adapters.agno` | `>=2.0.0` (patches `FunctionCall.execute` / `aexecute`) | `2.6.x` |
| Microsoft Agent Framework | `agent_framework` | `agent_assembly.adapters.microsoft_agent_framework` | `>=1.0.0,<2.0` | `1.9.x` — see [note below](#microsoft-agent-framework-version-range) |

!!! note "Adapter present vs. example present"
    Every framework above has an adapter that is implemented and registered —
    `init_assembly()` detects and hooks the framework whenever it is installed. Whether a
    *runnable end-to-end example* exists for each is tracked separately in
    [Framework support](../examples/framework-support.md).

### Pydantic AI version range

The Pydantic AI adapter supports **both** the legacy and current framework lines: on
`<0.3.0` it patches the internal `pydantic_ai.tools.Tool._run` hook, and on `>=0.3.0`
(where that entry point was renamed) it patches `AbstractToolset.call_tool` plus the
concrete toolsets that override it. The hook point is auto-detected at
`init_assembly()` time, so a single adapter covers both.

The **tested line is `pydantic-ai>=0.3.0`** — that is the version installed by the SDK's
own dev/test dependency group and exercised by the `importorskip`-guarded integration
test, so it is the line we continuously validate. Earlier `0.1.x`–`0.2.x` releases still
work through the `Tool._run` hook but are not exercised in CI.

> **Note on older docs:** an earlier revision of the
> [Pydantic AI example](../examples/pydantic-ai.md) pinned `pydantic-ai>=0.1.0,<0.3.0`
> and stated that governance hooks only attach on the `0.1.x`–`0.2.x` line. That
> predated the `>=0.3.0` `AbstractToolset.call_tool` support and is no longer accurate;
> the example and that pin now track the tested `>=0.3.0` line.

### LlamaIndex hook point

The LlamaIndex adapter patches the concrete `FunctionTool.call` (sync) and
`FunctionTool.acall` (async) tool-execution methods — the exact path the agent loop
drives. The modern agent stack (`FunctionAgent` / `ReActAgent` via `AgentWorkflow`)
awaits `tool.acall(...)`, while legacy / sync callers use `tool.call(...)`; both are
hooked so a denied tool's underlying function never runs. The base
`BaseTool.call`/`acall` are abstract, so the patch targets the concrete `FunctionTool`
rather than the base class. On a deny verdict the adapter returns a `ToolOutput` flagged
`is_error=True` so the agent loop receives a well-formed result instead of crashing.

The **tested line is `llama-index-core>=0.10.0`** (the `0.14.x` line is exercised by the
`importorskip`-guarded tests and the live smoke suite).

### Agno (formerly Phidata)

Agno (pip `agno`; the package was previously published as `phidata`) routes **every**
function-tool body through a single chokepoint: `agno.tools.function.FunctionCall.execute`
(sync) and `FunctionCall.aexecute` (async). An `Agent` builds a `FunctionCall` from the
model's tool-call request and invokes that method, which runs the user's tool entrypoint
and wraps the return in a `FunctionExecutionResult`.

The Agno adapter patches that one method, so the pre-execution governance check runs
*before* the tool body. A `deny` short-circuits the body entirely — the tool never runs —
and returns a `FunctionExecutionResult(status="failure", ...)` carrying the block message,
which Agno surfaces to the model as a tool error. An `allow` runs the body and records the
result. The **tested line is `agno>=2.0.0`** (currently `2.6.x`), installed by the SDK's
dev/test dependency group and exercised by the `importorskip`-guarded integration test.

### Microsoft Agent Framework version range

Microsoft's unified **Agent Framework** ships on PyPI as `agent-framework` but imports
as the top-level module **`agent_framework`** — so the adapter's `is_available()` probes
`agent_framework`, not its framework name. The single interception point is
`agent_framework.FunctionTool.invoke`, the async coroutine through which **every**
function tool executes (both `@agent_framework.tool`-decorated callables and direct
`FunctionTool(...)` instances). Patching that one method governs all tool execution
without requiring the user to register any framework middleware.

The **tested line is `agent-framework>=1.9.0`** — the first stable 1.x line. The adapter
pins `>=1.0.0,<2.0`; the 2.x surface is unverified. The package is **pre-release-heavy**:
several of its sub-distributions (`agent-framework-azure-ai-search`, etc.) are published
as pre-releases, so an installer that does not allow pre-releases (notably `uv`) needs an
explicit pre-release opt-in (e.g. `uv pip install --prerelease=allow agent-framework`).
`pip install agent-framework` resolves them without a flag.

## Declaring frameworks in your own project

The frameworks above are **not** runtime dependencies of `agent-assembly` — installing
the SDK does not pull in LangChain, CrewAI, and so on. You install whichever framework
your agent already uses, alongside the SDK, and the matching adapter activates
automatically:

```bash
pip install agent-assembly langchain   # or crewai, pydantic-ai, mcp, openai-agents, smolagents, ...
```

The SDK deliberately does **not** declare these frameworks as `pip install
agent-assembly[langchain]`-style optional extras: the agent framework is the user's own
choice and version, the SDK governs whatever is importable, and pinning a framework as an
extra would imply the SDK owns its version. Pin the framework yourself, within the
**Supported range** above.

## How this matrix is kept in sync

This table is sourced from two places that are the actual source of truth, so it does not
drift silently:

- **Supported range** ← each adapter's `get_supported_versions()` in
  `agent_assembly/adapters/<framework>/adapter.py`.
- **Tested version** ← the framework pins in the SDK's `pyproject.toml` `test`
  dependency group and the live smoke suite (AAASM-3525).

When an adapter's supported range changes or a tested-version pin is bumped, update the
corresponding row here.
