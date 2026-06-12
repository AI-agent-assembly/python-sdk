# Guides

Task-focused walkthroughs for using the SDK in real projects. If you're just getting started,
do the [Quick Start](../quick-start.md) first.

| Guide | What it covers |
| --- | --- |
| [Framework examples](framework-examples.md) | Wire the SDK into LangChain (validated, offline example) and the other supported frameworks; the universal `init_assembly()` pattern; adapter detection and priority. |
| [Handling allow/deny decisions](handling-decisions.md) | Catch a policy denial, the exception hierarchy, MCP-specific blocks, and observe (dry-run) mode. |
| [Type checking](type-checking.md) | Use the SDK's shipped types (PEP 561) with mypy / Pyright in your own project. |

For the *why* behind the design — the adapter pattern, modes, and lifecycle — see
[Core Concepts](../concepts/index.md).
