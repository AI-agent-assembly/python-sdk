# Contributing to Agent Assembly Python SDK

Thanks for your interest in improving the Agent Assembly Python SDK. This document is the entry point for everything a contributor needs: how to set up the dev environment, how to add a new framework adapter, what tests and linters to run, and how to open a pull request that will be merged quickly.

## Table of contents

- [Development environment](#development-environment)
- [Adding a new framework adapter](#adding-a-new-framework-adapter)
- [Running tests and lints](#running-tests-and-lints)
- [Branch naming and commit style](#branch-naming-and-commit-style)
- [Pull request checklist](#pull-request-checklist)

## Development environment

### Prerequisites

- **Python** ≥ 3.12 (the CI matrix exercises 3.12, 3.13, and 3.14)
- **uv** ≥ 0.4 — used to manage the virtualenv and lockfile (`pyproject.toml` + `uv.lock`)
- **Rust** stable channel — only required if you plan to build the optional native extension (`rust/aa-ffi-python/`); pure-Python development works without it
- **pre-commit** — installed automatically as a dev dependency; activate with `uv run pre-commit install`

### One-time setup

```bash
git clone https://github.com/AI-agent-assembly/python-sdk.git
cd python-sdk
uv sync                           # creates .venv and installs runtime + dev dependencies
uv run pre-commit install         # wires pre-commit hooks into your git config
```

If you want the native fast path, build the PyO3 extension into the same venv:

```bash
uv tool run maturin develop --manifest-path rust/aa-ffi-python/Cargo.toml --release
```

After this, `from agent_assembly._core import RuntimeClient` should succeed inside `uv run python`.

### Working in a worktree (optional)

For isolated feature work, create a `git worktree` so multiple branches can be developed in parallel without context-switching the main checkout:

```bash
git fetch remote && git checkout master && git pull --ff-only remote master
git worktree add -b v0.0.0/AAASM-XXXX/short_summary ../python-sdk-AAASM-XXXX-short_summary master
```

Each worktree gets its own `.venv` — re-run `uv sync` inside the worktree before running tests.

## Adding a new framework adapter

Framework adapters are the SDK's mechanism for governing third-party agent frameworks (LangChain, CrewAI, OpenAI Agents, etc.) without forcing those frameworks to be aware of Agent Assembly. Every adapter implements the [`FrameworkAdapter`](./agent_assembly/adapters/base.py) ABC.

### 1. Decide where the adapter lives

Adapters live under `agent_assembly/adapters/<framework_name>/`. Match the directory name to the framework's import name (e.g. `langchain`, `crewai`, `openai_agents`).

### 2. Implement the four required methods

```python
from agent_assembly.adapters.base import FrameworkAdapter, GovernanceInterceptor


class MyFrameworkAdapter(FrameworkAdapter):
    def get_framework_name(self) -> str:
        return "my-framework"

    def get_supported_versions(self) -> list[str]:
        return [">=1.0.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        # Install monkey-patches that route framework calls through interceptor.
        ...

    def unregister_hooks(self) -> None:
        # Revert all patches installed by register_hooks().
        ...
```

`register_hooks()` typically delegates to one or more `RuntimePatch` instances (see ADR-0001 in `docs/development/adr/0001-hook-architecture.md`). `unregister_hooks()` must be idempotent and must revert patches in reverse install order.

### 3. Register the adapter for auto-discovery

Add an entry to `agent_assembly/adapters/registry.py` so `init_assembly()` picks up your adapter automatically when the underlying framework is importable. Tests under `test/unit/adapters/` enforce that every registered adapter is constructible and reports a non-empty framework name.

### 4. Validate the adapter

Run the in-tree validator:

```bash
uv run aasm adapter-validate my-framework
```

The validator checks the ABC contract, version range syntax, and round-trip behaviour (`register_hooks` → `unregister_hooks` leaves no residue).

### 5. Write tests

Each adapter must have:

- A unit test under `test/unit/adapters/<framework_name>/` covering the patch install/revert lifecycle (mock the framework's classes).
- An integration test under `test/integration/adapters/<framework_name>/` that exercises a minimal end-to-end flow with the real framework imported.

