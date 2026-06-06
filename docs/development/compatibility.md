# Compatibility

How the Python SDK stays aligned with the **core runtime** (`agent-assembly`) and which
Python versions it supports.

## Python versions

| | |
| --- | --- |
| Supported | Python **3.12, 3.13, 3.14** (`requires-python = ">=3.12,<4.0"`) |
| Tested in CI | 3.12 – 3.14 across Linux and macOS |

The SDK uses modern typing (PEP 695 `type` aliases, PEP 604 unions), so 3.12 is the floor.

## How the SDK tracks the core runtime

The SDK has two layers, and each aligns with the core runtime differently:

### Pure-Python client

The pure-Python `GatewayClient` talks to a running gateway over its network protocol. It is
forward/backward tolerant within a protocol generation — unknown fields are ignored — so a
client can talk to a gateway that is a few patch versions ahead or behind. The wire contract
it targets is the gateway's HTTP/gRPC API in the core runtime.

### Native extension (pinned)

The optional native extension (`agent_assembly._core`) is built from Rust crates **pinned to
an exact core-runtime commit**. All three shared crates resolve to a single git SHA so they
share one protocol definition (ADR-0002 / AAASM-2559):

```toml
# rust/aa-ffi-python/Cargo.toml
aa-core       = { git = ".../agent-assembly.git", rev = "<sha>", package = "aa-core" }
aa-proto      = { git = ".../agent-assembly.git", rev = "<sha>", package = "aa-proto" }
aa-sdk-client = { git = ".../agent-assembly.git", rev = "<sha>", package = "aa-sdk-client" }
```

**The pinned `rev` is the source of truth** for which core-runtime revision a given native
wheel is wire-compatible with. To find it, read the `rev` in
[`rust/aa-ffi-python/Cargo.toml`](https://github.com/AI-agent-assembly/python-sdk/blob/master/rust/aa-ffi-python/Cargo.toml)
and compare it against the [core runtime history](https://github.com/AI-agent-assembly/agent-assembly/commits/master).

## Shared wire semantics

Where the SDK mirrors core-runtime types, it uses the same on-the-wire tokens so payloads
round-trip without translation. For example, `enforcement_mode` (`enforce` / `observe` /
`disabled`) mirrors `aa_core::EnforcementMode`, and the audit dataclasses
(`AuditEvent`, `CallStackNode`) mirror the `assembly.audit.v1` proto messages field-for-field
in snake_case.

## Upgrading

- **Pure-Python only** — upgrade `agent-assembly` from PyPI freely; pin an exact version if you
  need a frozen contract (the project is pre-1.0; see [Project status](https://github.com/AI-agent-assembly/python-sdk#project-status)).
- **Native path** — a new native wheel may advance the pinned core-runtime SHA. If you run a
  self-managed gateway, keep it within the same protocol generation as the pinned `rev`.

See the core runtime's [README](https://github.com/AI-agent-assembly/agent-assembly#readme) for
the protocol specification and the gateway side of this contract.
