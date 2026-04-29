# Agent Assembly Python SDK

Python SDK for AI Agent Assembly, providing a simple client for connecting agents to a governance gateway.

## Requirements

- Python `>=3.12,<4.0`

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
