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
