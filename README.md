# Agent Assembly Python SDK

[![PyPI version](https://img.shields.io/pypi/v/agent-assembly.svg)](https://pypi.org/project/agent-assembly/)
[![Python versions](https://img.shields.io/pypi/pyversions/agent-assembly.svg)](https://pypi.org/project/agent-assembly/)
[![CI](https://github.com/AI-agent-assembly/python-sdk/actions/workflows/ci.yaml/badge.svg?branch=master)](https://github.com/AI-agent-assembly/python-sdk/actions/workflows/ci.yaml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

Python SDK for **AI Agent Assembly** — a governance-native runtime for AI agents. One `init_assembly()` call wires your agent into the policy gateway, applies pre-execution allow/deny on tool calls, and emits audit events without changing how the agent itself is written.

## Why use it

- **Framework adapters** for LangChain, LangGraph, CrewAI, OpenAI Agents, Pydantic AI, and MCP servers — drop in, no SDK rewrites required.
- **Pre-execution policy enforcement** via the `FrameworkAdapter` ABC — block disallowed tool calls before they hit the LLM.
- **Audit trail** — every tool call, prompt, and policy decision is emitted to the gateway with full agent lineage (parent / root / team).
- **Native PyO3 fast path** (optional) — drop into a Rust runtime client when you need sub-millisecond policy checks.
- **Typed throughout** — Pydantic models for every gateway payload, mypy strict on adapter base and registry.

## Requirements

- **Python** `>=3.12,<4.0` (3.12, 3.13, 3.14 are tested in CI)
- **Rust toolchain** (stable channel) — only required for building the optional native extension via `maturin develop`. Pure-Python users do not need Rust.
- **uv** ≥ 0.4 — recommended for managing the dev environment. (`pip` works for plain installs.)

## Installation

From source:

```bash
pip install git+https://github.com/AI-agent-assembly/python-sdk.git
```

For local development:

```bash
uv sync
```

## Quick Start

```python
import asyncio

from agent_assembly import init_assembly


async def main() -> None:
    context = init_assembly(
        gateway_url="http://localhost:8080",
        api_key="required-api-key",
        agent_id="my-agent-001",
        mode="auto",
    )

    try:
        registration = await context.client.register_agent()
        decision = await context.client.check_policy_compliance("tool.call")
        print(registration)
        print(decision)
    finally:
        context.shutdown()


asyncio.run(main())
```

## Public API

- `init_assembly(gateway_url, api_key, agent_id=None, mode="auto") -> AssemblyContext`
- `GatewayClient.register_agent() -> dict`
- `GatewayClient.check_policy_compliance(action: str) -> dict`
- Exceptions: `AssemblyError`, `AgentError`, `PolicyError`, `GatewayError`, `ConfigurationError`
- Data models: `AgentConfig`, `AgentState`, `PolicyEvaluation`

## Error Handling

```python
from agent_assembly import init_assembly
from agent_assembly.exceptions import ConfigurationError

try:
    context = init_assembly(gateway_url="", api_key="my-api-key", agent_id="my-agent-001")
except ConfigurationError as exc:
    print(f"Invalid configuration: {exc}")
```

## Development

Run tests:

```bash
uv run pytest
```

Run integration tests:

```bash
uv run pytest -m integration
```

Lint and type-check:

```bash
uv run ruff check .
uv run mypy agent_assembly
```

## Native Core Extension (AAASM-55)

Build and install the PyO3 extension locally:

```bash
uv tool run maturin develop --manifest-path rust/aa-ffi-python/Cargo.toml --release
```

Validate native module import:

```python
from agent_assembly._core import RuntimeClient, GovernanceEvent, PolicyResult
```

Run opt-in native integration tests:

```bash
AAASM_RUN_NATIVE_CORE_TESTS=1 uv run pytest test/integration/test_native_core_runtime.py
AAASM_RUN_MATURIN_TESTS=1 uv run pytest test/integration/test_native_core_maturin.py
```

## Documentation

- Project docs source: `docs/`

## License

[MIT License](./LICENSE)
