# Verification Report — AAASM-2561

**Story:** AAASM-2561 — ♻️ (python-sdk): Thin Python pyo3 shim over `aa-sdk-client` (retire fat binding copy)
**Epic:** AAASM-2552 — SDK security boundary + FFI consolidation (boundary-first)
**ADR:** [`agent-assembly/docs/src/adr/0002-sdk-security-boundary.md`](https://github.com/ai-agent-assembly/agent-assembly/blob/master/docs/src/adr/0002-sdk-security-boundary.md)
**Component:** `python-sdk` — binding at `rust/aa-ffi-python/`
**Date:** 2026-06-06

---

## Summary

The Python SDK's PyO3 binding is now a **thin shim** over the shared `aa-sdk-client` crate. The runtime-client logic — UDS transport, IPC wire codec, and the `AssemblyClient` lifecycle — lives once in `aa-sdk-client` (git-SHA pinned to agent-assembly `9cf8a033`); the binding only provides the ergonomic Python surface, type translation, and event capture. It holds **no** security authority: advisory, non-authoritative credential preflight is provided transitively by `aa-sdk-client`, and `aa-runtime` re-scans every event authoritatively.

`rust/aa-ffi-python/src/lib.rs` shrank from **719 → ~292 lines** (−497 net in the delegation commit).

## Subtasks / PRs (one PR per subtask, stacked, base `master`)

| Subtask | PR | Scope |
| --- | --- | --- |
| AAASM-2640 | [#79](https://github.com/ai-agent-assembly/python-sdk/pull/79) | Pin shared crates + add `aa-sdk-client`; delegate `RuntimeClient` to `aa_sdk_client::AssemblyClient`; release the GIL during `send_event` |
| AAASM-2641 | [#80](https://github.com/ai-agent-assembly/python-sdk/pull/80) | Drop `PolicyResult`/`PolicyTimeoutError` from `_core` exports; align native tests + docs; valid `AuditEntry` payload in the FFI benchmark |
| AAASM-2642 | this PR | Verification + report |

## Acceptance criteria

| # | Criterion | Result |
| --- | --- | --- |
| 1 | Python binding is a thin pyo3 shim over `aa-sdk-client` | ✅ `RuntimeClient.connect/send_event/close` delegate to `aa_sdk_client::AssemblyClient` (`spawn_ipc_thread` + `report_event` + `shutdown`). No local transport remains. |
| 1 | `uv sync` + `pytest` green | ✅ 418 passed, 10 skipped (pure-Python install; native + optional-framework tests skip). |
| 1 | PyO3 extension builds | ✅ `maturin develop` builds + installs `agent_assembly._core` (CPython 3.13, arm64). `cargo build` compiles with zero warnings; extension links with `-undefined dynamic_lookup` (as maturin sets). |
| 2 | Runtime-client logic lives once in `aa-sdk-client`; no duplicate | ✅ The tokio worker loop, frame codec, varint helpers, and synchronous `query_policy` round-trip are deleted from the binding. |
| 3 | The shim holds no authoritative security logic | ✅ The binding does not depend on `aa-security`; advisory preflight comes from `aa-sdk-client` (feature `preflight`, default on). Policy/approval is server-side per the ADR trust model. |

## Native `_core` surface (built module)

```
exports: ['GovernanceEvent', 'RuntimeClient', 'audit_event_from_wire_bytes', 'audit_event_to_wire_bytes']
RuntimeClient methods: ['close', 'connect', 'send_event', 'socket_path']
PolicyResult present? False
agent_assembly.__all__ has RuntimeClient? True | PolicyResult? False
```

## Verification commands & results

| Check | Result |
| --- | --- |
| `cargo build` (rust/) | compiles, **0 warnings**; final link via `-undefined dynamic_lookup` produces `libaa_ffi_python.dylib` |
| `maturin develop --manifest-path rust/aa-ffi-python/Cargo.toml` | ✅ built + installed `agent_assembly._core` |
| `pytest` (pure-Python, CI path) | ✅ **418 passed, 10 skipped** |
| `AAASM_RUN_NATIVE_CORE_TESTS=1 pytest` (native built) | ✅ **426 passed, 4 skipped** |
| gated `test_native_core_runtime.py` (real UDS mock runtime) | ✅ `send_event` non-blocking, no thread deadlock, tracemalloc leak guard |
| `test_audit_event_wire_roundtrip.py` (native) | ✅ type-translation round-trips, incl. 3-level call stack |
| FFI benchmarks | ✅ `GovernanceEvent` construction ≈ 13.6 µs; `send_event` enqueue ≈ 41.7 µs (target < 2 ms) |

## Findings during verification

1. **GIL deadlock under the bounded channel (fixed — commit `12fe563`).** `aa-sdk-client` ships events over a *bounded* channel with a *blocking* send (the old binding used an unbounded channel). Delegating while holding the GIL deadlocks when the runtime peer is an in-process Python thread (the native test's mock runtime) and stalls other Python threads under backpressure in general. Fixed by releasing the GIL (`py.detach`) for the duration of the send. After the fix, all gated native tests pass with their original timing assertions intact.
2. **Pre-existing benchmark bug (fixed — commit `c0972d1`).** `GovernanceEvent` deserializes its argument as an `aa_core::AuditEntry`, but the FFI benchmark passed a non-`AuditEntry` dict, so it errored whenever the native module was built (it is skipped in CI, which hid it). Replaced with a valid `AuditEntry` payload so the benchmark exercises the real FFI path.

## Scope notes

- **`query_policy` removed from the native surface.** Per ADR 0002, the per-language shim is *"ergonomic API, hooks, type translation, event capture — no security authority,"* and the trust model places policy/approval server-side. `aa-sdk-client` is fire-and-forget event shipping + advisory preflight and intentionally has no synchronous policy round-trip. The native `query_policy`/`PolicyResult`/`PolicyTimeoutError` had no pure-Python callers (documented policy checks use the httpx gateway client); they were a SDK-side reimplementation of runtime-client logic that this Epic retires.
- Distribution is the git-SHA pin already in production (ADR 0002); no new infrastructure.
