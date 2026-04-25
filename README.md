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
    client = init_assembly(
        gateway_url="http://localhost:8080",
        agent_id="my-agent-001",
        api_key="optional-api-key",
    )

    try:
        registration = await client.register_agent()
        decision = await client.check_policy_compliance("tool.call")
        print(registration)
        print(decision)
    finally:
        client.close()


asyncio.run(main())
```

## Public API

- `init_assembly(gateway_url, agent_id, api_key=None) -> GatewayClient`
- `GatewayClient.register_agent() -> dict`
- `GatewayClient.check_policy_compliance(action: str) -> dict`
- Exceptions: `AssemblyError`, `AgentError`, `PolicyError`, `GatewayError`, `ConfigurationError`
- Data models: `AgentConfig`, `AgentState`, `PolicyEvaluation`

## Error Handling

```python
from agent_assembly import init_assembly
from agent_assembly.exceptions import ConfigurationError

try:
    client = init_assembly(gateway_url="", agent_id="my-agent-001")
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

## Documentation

- Project docs source: `docs/`

## License

[MIT License](./LICENSE)
