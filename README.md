# Agent Assembly Python SDK

[![PyPI version](https://img.shields.io/pypi/v/agent-assembly.svg)](https://pypi.org/project/agent-assembly/)
[![Python versions](https://img.shields.io/pypi/pyversions/agent-assembly.svg)](https://pypi.org/project/agent-assembly/)
[![CI](https://github.com/ai-agent-assembly/python-sdk/actions/workflows/ci.yaml/badge.svg?branch=master)](https://github.com/ai-agent-assembly/python-sdk/actions/workflows/ci.yaml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

Python SDK for **AI Agent Assembly** — a governance-native runtime for AI agents. One `init_assembly()` call wires your agent into the policy gateway, applies pre-execution allow/deny on tool calls, and emits audit events without changing how the agent itself is written.

## Why use it

- **Framework adapters** for LangChain, LangGraph, CrewAI, OpenAI Agents, Pydantic AI, and MCP servers — drop in, no SDK rewrites required.
- **Pre-execution policy enforcement** via the `FrameworkAdapter` ABC — block disallowed tool calls before they hit the LLM.
- **Audit trail** — every tool call, prompt, and policy decision is emitted to the gateway with full agent lineage (parent / root / team).
- **Native PyO3 fast path** (optional) — drop into a Rust runtime client when you need sub-millisecond policy checks.
- **Typed throughout** — Pydantic models for every gateway payload, mypy strict on adapter base and registry.

## Project status

**Pre-1.0 (`0.x`) — published and usable, API not yet frozen.** The SDK is released to
PyPI from the `0.0.x` line (the version badge above reflects the current release). Until
`1.0.0`, minor versions may introduce breaking changes to the public surface; pin an exact
version (`agent-assembly==0.0.x`) if you need a stable contract.

- **Releases** — [PyPI release history](https://pypi.org/project/agent-assembly/#history) · [GitHub releases](https://github.com/ai-agent-assembly/python-sdk/releases)
- **Changelog** — tracked via [commits to `master`](https://github.com/ai-agent-assembly/python-sdk/commits/master) until the first tagged `1.0` release; see the [release notes](https://ai-agent-assembly.github.io/python-sdk/latest/release-notes/) page.
- **Stability** — the `init_assembly()` entry point and the exception hierarchy are the most stable surface; framework adapters and the native fast path may evolve faster.

## Requirements

- **Python** `>=3.12,<4.0` (3.12, 3.13, 3.14 are tested in CI)
- **Rust toolchain** (stable channel) — only required for building the optional native extension via `maturin develop`. Pure-Python users do not need Rust.
- **uv** ≥ 0.4 — recommended for managing the dev environment. (`pip` works for plain installs.)

## Installation

### Use the SDK in your project

The package is published on PyPI as [`agent-assembly`](https://pypi.org/project/agent-assembly/):

```bash
pip install agent-assembly            # pure-Python SDK
pip install 'agent-assembly[runtime]' # SDK + bundled aasm runtime binary (platform wheel)
```

`agent-assembly[runtime]` pulls a platform wheel (`manylinux`, `macosx`) that bundles the
`aasm` sidecar binary, so you don't need a separate runtime install. Plain `agent-assembly`
is the pure-Python client and expects an `aasm` runtime to be reachable some other way.

With [`uv`](https://docs.astral.sh/uv/):

```bash
uv add agent-assembly
```

To track unreleased changes, install from the `master` branch:

```bash
pip install git+https://github.com/ai-agent-assembly/python-sdk.git
```

### Develop on the SDK

Clone the repo and sync the dev environment with `uv`:

```bash
git clone https://github.com/ai-agent-assembly/python-sdk.git
cd python-sdk
uv sync
```

To build the optional PyO3 extension locally (requires Rust):

```bash
uv tool run maturin develop --manifest-path native/aa-ffi-python/Cargo.toml --release
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
uv tool run maturin develop --manifest-path native/aa-ffi-python/Cargo.toml --release
```

Validate native module import:

```python
from agent_assembly._core import RuntimeClient, GovernanceEvent
```

Run opt-in native integration tests:

```bash
AAASM_RUN_NATIVE_CORE_TESTS=1 uv run pytest test/integration/test_native_core_runtime.py
AAASM_RUN_MATURIN_TESTS=1 uv run pytest test/integration/test_native_core_maturin.py
```

## Documentation

- **Project docs (rendered)** — https://ai-agent-assembly.github.io/python-sdk/ *(versioned via `mike`; pick `latest` or `stable` from the version selector)*
- **Architecture** — [rendered](https://ai-agent-assembly.github.io/python-sdk/latest/architecture/) / [source](./docs/architecture/index.md) — adapter pattern, PyO3 FFI, `init_assembly()` lifecycle, with a Mermaid flow diagram.
- **Usage guides** — [Configuration](./docs/usage/configuration.md), [Framework examples](./docs/usage/framework-examples.md), [Type checking](./docs/usage/type-checking.md).
- **API reference** — [rendered](https://ai-agent-assembly.github.io/python-sdk/latest/api-reference/) / [source](./docs/api-reference/index.md) — auto-generated from package docstrings via `mkdocstrings`. Per-module pages: [Client](./docs/api-reference/client.md), [Exceptions](./docs/api-reference/exceptions.md), [Models](./docs/api-reference/models.md).
- **Development** — [Troubleshooting](./docs/development/troubleshooting.md), [Compatibility](./docs/development/compatibility.md), [Release process](./docs/development/release-process.md), and [ADRs](./docs/development/adr/) (architecture decision records).

## Ecosystem

This SDK is one piece of the **AI Agent Assembly** project. Start from the
[organization profile](https://github.com/ai-agent-assembly) to discover every repo, or jump
directly:

| Project | What it is |
| --- | --- |
| [agent-assembly](https://github.com/ai-agent-assembly/agent-assembly) | **Core runtime** — gateway, policy engine, eBPF, proxy, CLI. Also home of the protocol specification. |
| [Documentation site](https://ai-agent-assembly.github.io/agent-assembly-docs/) | Canonical, cross-repo documentation hub for the whole project. |
| [python-sdk](https://github.com/ai-agent-assembly/python-sdk) | **This repo** — the Python SDK. |
| [node-sdk](https://github.com/ai-agent-assembly/node-sdk) · [go-sdk](https://github.com/ai-agent-assembly/go-sdk) | Sibling SDKs for TypeScript/Node and Go. |
| [homebrew-agent-assembly](https://github.com/ai-agent-assembly/homebrew-agent-assembly) | Homebrew tap for installing the `aasm` runtime CLI. |

The protocol specification and gateway behaviour the SDK targets live in the core runtime
monorepo; see its [README](https://github.com/ai-agent-assembly/agent-assembly#readme) for the
spec and architecture. For how this SDK stays in sync with the core runtime, see the
[Compatibility](https://ai-agent-assembly.github.io/python-sdk/latest/development/compatibility/)
doc.

## Contributing

Please read [**CONTRIBUTING.md**](./CONTRIBUTING.md) before opening a PR — it covers dev environment setup, framework adapter authoring, the test/lint command list, branch naming, and the PR checklist.

## Support

- **Bugs & feature requests** — open a [GitHub issue](https://github.com/ai-agent-assembly/python-sdk/issues).
- **Questions & usage help** — start with the [documentation site](https://ai-agent-assembly.github.io/python-sdk/) and the [Troubleshooting](https://ai-agent-assembly.github.io/python-sdk/latest/development/troubleshooting/) guide, then open an issue if you're still stuck.
- **Security** — please **do not** file public issues for vulnerabilities. Report them privately via [GitHub Security Advisories](https://github.com/ai-agent-assembly/python-sdk/security/advisories/new).

## License

[MIT License](./LICENSE)
