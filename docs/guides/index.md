# Guides

Task-focused walkthroughs for using the SDK in real projects. If you're just getting started,
do the [Quick Start](../quick-start.md) first.

| Guide | What it covers |
| --- | --- |
| [Handling allow/deny decisions](handling-decisions.md) | Catch a policy denial, the exception hierarchy, MCP-specific blocks, and observe (dry-run) mode. |
| [Authoring a framework adapter](authoring-adapters.md) | Build, test, and publish a `FrameworkAdapter` for a new framework — interface reference, hook patterns, the contract validator, and entry-point publishing. |
| [Type checking](type-checking.md) | Use the SDK's shipped types (PEP 561) with mypy / Pyright in your own project. |

For runnable, end-to-end framework integrations — LangChain, LangGraph, CrewAI, OpenAI Agents,
Pydantic AI, Google ADK, LlamaIndex, and a framework-free example — see the
[Examples](../examples/index.md) section. [Framework support](../examples/framework-support.md)
there covers the universal `init_assembly()` pattern, adapter detection, and priority.

For the *why* behind the design — the adapter pattern, modes, and lifecycle — see
[Core Concepts](../concepts/index.md).
