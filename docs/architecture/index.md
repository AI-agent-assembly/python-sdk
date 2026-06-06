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

The native crate lives at `rust/aa-ffi-python/` in the repository and is built with [`maturin`](https://www.maturin.rs/). When installed, it exposes a private `agent_assembly._core` module with two symbols:

- `RuntimeClient` — a Rust-backed runtime client (a thin shim over the shared `aa-sdk-client` crate) that ships governance events to `aa-runtime` over the local socket. Sub-millisecond, fire-and-forget event reporting under load.
- `GovernanceEvent` — Rust-side dataclass for events emitted on the audit channel.

`agent_assembly/__init__.py` imports these symbols inside a `try / except ImportError` block. **If the native extension was never built, the SDK still works** — pure-Python `GatewayClient` is the fallback, and the `RuntimeClient` symbol simply is not present in `agent_assembly.__all__`.

### When to build it

Run the maturin build only if you need the native fast path:

```bash
uv tool run maturin develop --manifest-path rust/aa-ffi-python/Cargo.toml --release
```

For most contributors, this is unnecessary — the pure-Python SDK is the default development path, and CI exercises both with and without the native extension via the `AAASM_RUN_NATIVE_CORE_TESTS` and `AAASM_RUN_MATURIN_TESTS` environment-variable gates documented in [CONTRIBUTING.md](https://github.com/AI-agent-assembly/python-sdk/blob/master/CONTRIBUTING.md).

## `init_assembly()` lifecycle

`agent_assembly.init_assembly()` is the single entry point. Its job is to wire the SDK into the host process atomically — either everything succeeds and the agent is governed, or nothing was changed and the user sees an exception. It must never leave the process in a partially-patched state.

### Bootstrap order

1. **Validate inputs** (`gateway_url`, `api_key`, `mode`). Invalid arguments raise `ConfigurationError` *before* any side-effect runs, so retry logic in user code is safe.
2. **Create the gateway client** — pure-Python `GatewayClient` by default. If `mode != "sdk-only"` and the native extension is available, the assembly may switch to the Rust `RuntimeClient` (transparent to the caller).
3. **Discover adapters** via `AdapterRegistry.get_available_adapters_by_priority()`. Adapters whose underlying framework is not importable are silently skipped — no warning noise.
4. **Install hooks** by calling `adapter.register_hooks(interceptor)` for each available adapter, in priority order. Each adapter records the patches it owns so they can be reverted in step 9.
5. **Start the network layer** (the side-channel that streams audit events to the gateway). For `mode="ebpf"` and `mode="proxy"`, this is where the network sidecar handshake happens.
6. **Register the active context** in a process-global slot under a lock — `init_assembly()` is idempotent within a process: a second call returns the active context unchanged rather than double-installing hooks.
7. Return the [`AssemblyContext`](../api-reference/index.md) to the caller.

### Shutdown order (reverse)

The returned `AssemblyContext` doubles as a context manager (`__enter__` / `__exit__`). On `shutdown()`:

8. **Stop the network layer** — flush in-flight audit events.
9. **`unregister_hooks()` on every adapter, in reverse install order** — guarantees that nested patches (e.g. LangGraph wrapping LangChain) come off in the order opposite to install.
10. **Close the gateway client** — drain the HTTP keep-alive pool.
11. **Clear the process-global active-context slot** — the next `init_assembly()` call starts clean.

If any of steps 8–10 raises, the others still run; the exceptions are aggregated into a single `AssemblyError` raised at the end of `shutdown()`. This guarantees no patch is left installed even when teardown is messy.

### Why a single entry point

The SDK deliberately exposes only one bootstrap function. There is no "init the gateway client without installing hooks" or "install hooks only for adapter X" public API — those would let user code drift into a partially-patched state where some tool calls are governed and others are not. The single-entry-point design makes the trust boundary uniform: either `init_assembly()` succeeded and **every** registered framework is governed, or it raised and **none** of them are.
