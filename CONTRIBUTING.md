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
- **Rust** stable channel — only required if you plan to build the optional native extension (`native/aa-ffi-python/`); pure-Python development works without it
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
uv tool run maturin develop --manifest-path native/aa-ffi-python/Cargo.toml --release
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

## Running tests and lints

All commands run inside the project venv via `uv run`. CI runs the same commands — green CI is required before merge.

### Tests

```bash
uv run pytest                                 # full Python suite (auto-detects pytest.ini)
uv run pytest test/unit/cli/test_loader.py    # one file
uv run pytest -m integration                  # integration markers only
uv run pytest --benchmark-only test/bench/    # performance benchmarks
```

If you have built the native extension, two opt-in suites exercise the PyO3 layer:

```bash
AAASM_RUN_NATIVE_CORE_TESTS=1 uv run pytest test/integration/test_native_core_runtime.py
AAASM_RUN_MATURIN_TESTS=1 uv run pytest test/integration/test_native_core_maturin.py
```

The Rust crate has its own test suite:

```bash
cargo test --manifest-path native/aa-ffi-python/Cargo.toml
```

### Lint and format

```bash
uv run ruff check .                  # lint (config: ruff.toml; line length 120, target py312)
uv run ruff format .                 # auto-format
uv run mypy agent_assembly           # type check (mypy.ini; strict on adapters.base/registry)
uv run pre-commit run --all-files    # full pre-commit suite (isort + black + autoflake + mypy)
```

Pre-commit hooks block commits that fail any of the above. Do not bypass with `--no-verify`; fix the underlying issue.

## Branch naming and commit style

- **Branch**: `<release-or-phase>/<ticket>/<short_summary>` — e.g. `v0.0.0/AAASM-1122/author_readme_contributing`. Type slug optional but recommended (`feat`, `fix`, `refactor`, `test`, `docs`, `config`, `deps`, `remove`, `lint`).
- **Base branch**: always `master`. Never branch from another feature branch.
- **Push remote**: `remote` (= `https://github.com/AI-agent-assembly/python-sdk`). Never push feature branches to `origin` (the personal fork).
- **Commit message format**: `<gitemoji> (<scope>): <imperative summary under 72 chars>` — e.g. `📝 (readme): Add badge strip`. See [gitmoji.dev](https://gitmoji.dev/) for the full emoji table.
- **One concern per commit.** Each commit must be bisectable: tests pass, build succeeds. Prefer many small commits over one large commit.

## Pull request checklist

Before requesting review, confirm every item below.

- [ ] PR title is `[AAASM-XXXX] <emoji> (<scope>): <imperative summary>` (matches the commit style)
- [ ] PR body filled in from `.github/PULL_REQUEST_TEMPLATE.md` (Description, Type of Change, Breaking Changes, Related Issues, Testing, Checklist)
- [ ] Branch is up to date with `master` (rebased, not merged)
- [ ] `uv run pytest` is green locally (full suite, not just impacted tests)
- [ ] `uv run pre-commit run --all-files` is green
- [ ] `uv run mypy agent_assembly` is green
- [ ] If adapters or runtime changed: added/updated tests under `test/unit/` and `test/integration/`
- [ ] If public API changed: docstrings updated (mkdocstrings will pick them up automatically)
- [ ] If user-facing behaviour changed: README.md / docs/ updated
- [ ] No `print()` / `breakpoint()` / commented-out dead code left in the diff
- [ ] No `.env`, secrets, or large binaries staged

After opening: address all reviewer comments, keep CI green. Squash-merge is the project default.
