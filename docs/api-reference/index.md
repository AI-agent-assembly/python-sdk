# API Reference

Every symbol below is rendered **directly from the package source** by
[`mkdocstrings`](https://mkdocstrings.github.io/) — the signatures and docstrings here are the
ones in the installed `agent_assembly` package, never hand-copied, so they can't drift out of
date.

## Start here

If you've read [Quick Start](../quick-start.md) and [Core Concepts](../concepts/index.md), these
are the symbols you'll reach for most:

| Symbol | Import | What it is |
| --- | --- | --- |
| `init_assembly()` | `from agent_assembly import init_assembly` | The single entry point — wires governance into your process. Reference rendered on the [top-level package](#top-level-package) section below. |
| `AssemblyContext` | `from agent_assembly import AssemblyContext` | What `init_assembly()` returns; also a context manager. |
| `AssemblyError` & subtypes | `from agent_assembly import AssemblyError, ToolExecutionBlockedError, …` | The [exception hierarchy](exceptions.md) — what to catch. |
| `AuditEvent`, `CallStackNode` | `from agent_assembly.types import AuditEvent, CallStackNode` | Wire types from the audit trail. |

!!! tip "Where to import from"
    Import `init_assembly` and the exception types from the **top-level** `agent_assembly`
    package. Import data types from their defining submodule — `agent_assembly.types`,
    `agent_assembly.models`. This is what the SDK's own code does and what strict type checkers
    (mypy `--strict`, which enables `no-implicit-reexport`) expect. See
    [Type checking](../guides/type-checking.md).

## Per-module pages

- **[Client](client.md)** — `agent_assembly.client.GatewayClient`, the HTTP client that talks to the governance gateway.
- **[Exceptions](exceptions.md)** — the full exception hierarchy raised by the SDK (`AssemblyError`, `ToolExecutionBlockedError`, `MCPToolBlockedError`, …).
- **[Models](models.md)** — data models for gateway payloads (`AgentConfig`, `AgentState`, `PolicyEvaluation`).

## Top-level package

The public package surface — everything re-exported from `agent_assembly.__init__` — is rendered below. Use the per-module pages above for deep dives, and this page for a one-glance index of every public symbol.

::: agent_assembly
    options:
      show_root_heading: false
      show_root_toc_entry: false
      members_order: source
      show_submodules: false
      filters:
        - "!^_"
