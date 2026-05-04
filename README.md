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

### Use the SDK in your project

```bash
pip install agent-assembly
```

(Once published to PyPI. Until then, install directly from GitHub:)

```bash
pip install git+https://github.com/AI-agent-assembly/python-sdk.git
```

### Develop on the SDK

Clone the repo and sync the dev environment with `uv`:

```bash
git clone https://github.com/AI-agent-assembly/python-sdk.git
cd python-sdk
uv sync
```

To build the optional PyO3 extension locally (requires Rust):

```bash
uv tool run maturin develop --manifest-path rust/aa-ffi-python/Cargo.toml --release
```

The pure-Python SDK works without the native extension — `maturin develop` is only needed if you want the sub-millisecond `RuntimeClient` fast path.

## Quick Start

A governed LangChain ReAct agent that runs offline against a mock LLM. The example imports LangChain in addition to the SDK, so install both:

```bash
pip install agent-assembly langchain langchain-community
```

```python
from langchain.agents import AgentExecutor, create_react_agent
from langchain.tools import Tool
from langchain_community.llms import FakeListLLM
from langchain_core.prompts import PromptTemplate

from agent_assembly import init_assembly

with init_assembly(
    gateway_url="http://localhost:8080",
    api_key="dev-key",
    agent_id="quickstart-agent",
    mode="sdk-only",
):
    llm = FakeListLLM(responses=[
        "Thought: I should look up the user.\nAction: whoami\nAction Input: alice\n",
        "Thought: I have the answer.\nFinal Answer: alice is in engineering\n",
    ])
    tools = [Tool(name="whoami", func=lambda name: f"{name} is in engineering", description="who")]
    prompt = PromptTemplate.from_template(
        "Use the tools.\n{tools}\nTool names: {tool_names}\nQ: {input}\n{agent_scratchpad}"
    )
    executor = AgentExecutor(agent=create_react_agent(llm, tools, prompt), tools=tools, max_iterations=2)
    print(executor.invoke({"input": "Which team is alice on?"})["output"])
```

What this does:

1. `init_assembly()` registers the agent with the gateway and auto-loads the LangChain adapter — every tool call from now on goes through the policy gate.
2. The `FakeListLLM` replays canned responses so the example runs **offline** with no real LLM.
3. The `with` block tears down the gateway connection and unwinds adapter hooks on exit.

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

- **Project docs (rendered)** — https://ai-agent-assembly.github.io/python-sdk/ *(versioned via `mike`; pick `latest` or `stable` from the version selector)*
- **Architecture** — [`docs/architecture/`](./docs/architecture/) (adapter pattern, PyO3 FFI, `init_assembly()` lifecycle)
- **API reference** — [`docs/api-reference/`](./docs/api-reference/) (auto-generated from docstrings via `mkdocstrings`)
- **ADRs** — [`docs/development/adr/`](./docs/development/adr/) (architecture decision records)

## Contributing

Please read [**CONTRIBUTING.md**](./CONTRIBUTING.md) before opening a PR — it covers dev environment setup, framework adapter authoring, the test/lint command list, branch naming, and the PR checklist.

## License

[MIT License](./LICENSE)
