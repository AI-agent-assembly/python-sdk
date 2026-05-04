# Architecture

This page describes how the Agent Assembly Python SDK is put together internally — what each module does, how they relate, and where the boundaries are between Python, the Rust FFI layer, and the governance gateway.

It is aimed at three readers:

- **Contributors** about to add a new framework adapter or change one that exists.
- **Operators** evaluating the SDK who need to understand the trust boundary between user code and the policy gate.
- **Future maintainers** picking up the codebase a year from now.

## Sections

- [Adapter pattern](#adapter-pattern) — how the SDK intercepts a third-party agent framework.
- [PyO3 FFI layer](#pyo3-ffi-layer) — the optional native fast-path runtime client.
- [`init_assembly()` lifecycle](#init_assembly-lifecycle) — bootstrap order, sidecar handshake, and shutdown.

## Adapter pattern

The SDK governs *third-party* agent frameworks (LangChain, LangGraph, CrewAI, OpenAI Agents, Pydantic AI, MCP servers) without forcing those frameworks to be aware of Agent Assembly. The mechanism is a three-layer pattern:

### `FrameworkAdapter` (ABC) — the public interface

[`FrameworkAdapter`](../api-reference/index.md) at `agent_assembly.adapters.base` is an abstract base class that every framework adapter implements. It declares four lifecycle methods:

- `get_framework_name() -> str` — the framework's import name (e.g. `"langchain"`).
- `get_supported_versions() -> list[str]` — PEP 440 version specifiers.
- `register_hooks(interceptor) -> None` — install monkey-patches that route framework calls through the governance interceptor.
- `unregister_hooks() -> None` — revert all patches in reverse install order. Must be idempotent.

Adapter authors target this contract and nothing else. The public boundary is intentionally narrow so that adding a new framework does not require changes to the gateway client, the policy interceptor, or the registry's selection logic.

### `AdapterRegistry` — auto-discovery and priority ordering

`agent_assembly.adapters.registry.AdapterRegistry` enumerates the adapters that ship with the SDK, probes each one to see if its underlying framework is importable in the current process, and returns the available adapters in priority order. `init_assembly()` calls `get_available_adapters_by_priority()` exactly once at startup; this is the **single detection path** (see ADR-0001).

Priority matters because two frameworks can coexist in the same process — e.g., a LangGraph graph that contains a LangChain tool. The registry orders adapters so the more specific one (LangGraph) installs hooks before the more general one (LangChain), preventing duplicate event emission.

### Per-framework patches — the actual monkey-patching

Each adapter's `register_hooks()` delegates to one or more `RuntimePatch` objects (a `Protocol` defined in `agent_assembly.core.assembly`). A `RuntimePatch` knows how to apply and revert a single monkey-patch on a specific framework class or function. Examples:

- `agent_assembly.adapters.langchain.patch.LangChainPatch` — patches `BaseTool._run` and `BaseTool._arun` so every tool invocation passes through the governance gate.
- `agent_assembly.adapters.langchain.langgraph_patch.patch_stategraph_compile` — wraps `StateGraph.compile()` so the resulting graph's nodes are wrapped before any invocation.
- `agent_assembly.adapters.crewai.patch.CrewAIPatch` — analogous wrappers for CrewAI's tool invocation entry points.

This three-layer split keeps the public API stable (the ABC) while letting per-framework patch code change freely as those frameworks evolve. ADR-0001 captures the rationale.

### Visual

```mermaid
flowchart LR
    User["User code<br/>(LangChain / CrewAI / …)"]
    InitAssembly["init_assembly()"]
    Registry["AdapterRegistry<br/>get_available_adapters_by_priority()"]
    Adapter["FrameworkAdapter<br/>(LangChainAdapter, CrewAIAdapter, …)"]
    Patch["RuntimePatch<br/>(LangChainPatch, CrewAIPatch, …)"]
    Framework["Third-party framework<br/>(BaseTool._run, StateGraph.compile, …)"]
    Interceptor["GovernanceInterceptor"]
    Gateway["Gateway / policy engine"]

    User --> InitAssembly
    InitAssembly --> Registry
    Registry -->|enumerate available| Adapter
    Adapter -->|register_hooks(interceptor)| Patch
    Patch -->|monkey-patch| Framework
    Framework -.->|every tool call| Interceptor
    Interceptor -.->|allow/deny + audit| Gateway
```

Solid arrows are install-time; dashed arrows fire on every framework call after hooks are installed. The interceptor → gateway hop is the only network boundary in the data path.

## PyO3 FFI layer

The pure-Python adapters described above are sufficient for governing most agent frameworks. For deployments where every microsecond of policy-check latency matters — typically gateways under heavy multi-tenant load — the SDK ships an **optional** native runtime client written in Rust and exposed to Python via [PyO3](https://pyo3.rs/).

### What ships in the wheel

The native crate lives at `rust/aa-ffi-python/` in the repository and is built with [`maturin`](https://www.maturin.rs/). When installed, it exposes a private `agent_assembly._core` module with three symbols:

- `RuntimeClient` — a Rust-backed gateway client implementing the same protocol as `agent_assembly.client.GatewayClient`. Sub-millisecond policy checks under load.
- `GovernanceEvent` — Rust-side dataclass for events emitted on the audit channel.
- `PolicyResult` — Rust-side enum-like value returned from `RuntimeClient.evaluate(...)`.
- `PolicyTimeoutError` — raised when a policy check exceeds the configured deadline.

`agent_assembly/__init__.py` imports these symbols inside a `try / except ImportError` block. **If the native extension was never built, the SDK still works** — pure-Python `GatewayClient` is the fallback, and the `RuntimeClient` symbol simply is not present in `agent_assembly.__all__`.

### When to build it

Run the maturin build only if you need the native fast path:

```bash
uv tool run maturin develop --manifest-path rust/aa-ffi-python/Cargo.toml --release
```

For most contributors, this is unnecessary — the pure-Python SDK is the default development path, and CI exercises both with and without the native extension via the `AAASM_RUN_NATIVE_CORE_TESTS` and `AAASM_RUN_MATURIN_TESTS` environment-variable gates documented in [CONTRIBUTING.md](https://github.com/AI-agent-assembly/python-sdk/blob/master/CONTRIBUTING.md).
