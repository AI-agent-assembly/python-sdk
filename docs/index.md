# Agent Assembly Python SDK

Python SDK for **AI Agent Assembly** — a governance-native runtime for AI agents. One `init_assembly()` call wires your agent into the policy gateway, applies pre-execution allow/deny on tool calls, and emits audit events without changing how the agent itself is written.

## Why use it

- **Framework adapters** for LangChain, LangGraph, CrewAI, OpenAI Agents, Pydantic AI, and MCP servers — drop in, no SDK rewrites required.
- **Pre-execution policy enforcement** via the `FrameworkAdapter` ABC — block disallowed tool calls before they hit the LLM.
- **Audit trail** — every tool call, prompt, and policy decision is emitted to the gateway with full agent lineage (parent / root / team).
- **Native PyO3 fast path** (optional) — drop into a Rust runtime client when you need sub-millisecond policy checks.
- **Typed throughout** — Pydantic models for every gateway payload, mypy strict on adapter base and registry.

## Where to next

- **[Quickstart](https://github.com/AI-agent-assembly/python-sdk#quick-start)** — 5-minute LangChain ReAct example with a mock LLM (in the repo README).
- **[Architecture](architecture/)** — adapter pattern, PyO3 FFI layer, and the `init_assembly()` lifecycle.
- **[API reference](api-reference/)** — auto-generated from package docstrings via `mkdocstrings`.
- **[Development](development/)** — ADRs, contributor docs, and project conventions.

## Versions

This site is published with [`mike`](https://github.com/jimporter/mike) — use the version selector at the top of the page to switch between **stable** (the latest released version) and **latest** (the head of `master`). Older versions remain accessible at their pinned URLs.
