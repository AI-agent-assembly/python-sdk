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

