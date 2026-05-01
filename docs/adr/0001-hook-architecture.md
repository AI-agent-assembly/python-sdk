# ADR-0001: Canonical Hook Architecture

## Status

Accepted

## Context

The Python SDK needed a strategy for intercepting AI framework calls (LangChain,
LangGraph, CrewAI, Pydantic AI, OpenAI Agents, MCP) to enforce governance policies.

Two architectures were considered:

- **Architecture A (Python adapters)** — `FrameworkAdapter` ABC with
  `register_hooks()`/`unregister_hooks()`, `AdapterRegistry` with `auto_detect()`
  and entry-point discovery, per-framework patch classes with `apply()`/`revert()`.

- **Architecture B (Rust FFI hooks)** — Rust-level `HOOK_MODULES` constant mapping
  framework names to Python modules, `install_hooks()` Rust function calling
  `install(handle)` on each module.

Architecture B was planned but superseded by the AAASM-162 design decision before
implementation.

## Decision

**Python-side `.py` modules own monkey-patching and hook installation.
Rust owns IPC transport.**

### Layer responsibilities

| Layer | Owns | Does NOT own |
|---|---|---|
| Python adapters (`agent_assembly/adapters/`) | Framework detection, `auto_detect()`, monkey-patch installation/removal, framework-specific hook logic | IPC transport, protobuf serialization |
| Rust FFI (`agent_assembly/_core`) | IPC transport to sidecar (`RuntimeClient`), protobuf serialization, governance event types (`GovernanceEvent`, `PolicyResult`) | Framework detection, hook installation, monkey-patching |

### Two-level naming convention

The architecture uses two abstraction levels with distinct naming:

- **Public adapter API** — `FrameworkAdapter` ABC with `register_hooks(interceptor)`
  and `unregister_hooks()`. This is the interface SDK users and third-party plugin
  authors interact with. It represents "register governance hooks for this framework."

- **Internal patch mechanism** — `RuntimePatch` protocol with `apply()` and `revert()`.
  This is how monkey-patching is implemented internally. Each adapter's
  `register_hooks()` delegates to one or more `RuntimePatch` instances.

Both naming levels are intentional and serve different audiences.

### Single detection path

`AdapterRegistry.auto_detect()` is the single entry point for framework detection.
`init_assembly()` routes through the registry — there is no parallel detection path.

### Integration boundary

The adapter's `register_hooks()` method is where the two layers connect. Adapter
patches intercept framework calls and route them through the `GatewayClient` (or
`AssemblyCallbackHandler`) to the governance gateway. When the native Rust FFI
(`RuntimeClient`) is available, it provides the IPC transport; otherwise the
`GatewayClient` uses HTTP.

## Consequences

- No `hooks.rs`, `detect.rs`, or Rust-side `install()/uninstall()` will be built.
- Third-party framework adapters can be registered via Python entry points and will
  be automatically discovered by `init_assembly()`.
- All framework-specific patching logic remains in Python where it can be tested
  without compiling Rust.
