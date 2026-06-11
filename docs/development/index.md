# Development

Project conventions, contributor docs, and architecture decision records (ADRs) for the
Agent Assembly Python SDK. Start here when contributing code or operating a release.

## Contributor docs

| Page | What it covers |
| --- | --- |
| [CONTRIBUTING.md](https://github.com/ai-agent-assembly/python-sdk/blob/master/CONTRIBUTING.md) | Dev environment setup, framework adapter authoring, test/lint commands, branch naming, PR checklist. |
| [Troubleshooting](troubleshooting.md) | Common integration errors, what they mean, and how to fix them. |
| [Compatibility](compatibility.md) | Supported Python versions and how the SDK tracks the core runtime. |
| [Release process](release-process.md) | How a version goes from `master` to PyPI and the docs site. |

## Architecture decision records

ADRs capture the *why* behind major design choices so future maintainers can trace the
reasoning.

- [ADR-0001 — Hook architecture](adr/0001-hook-architecture.md) — why Python owns
  monkey-patching while Rust owns IPC transport.

## Quick command reference

```bash
uv sync                       # install deps + dev extras
uv run pytest                 # run the test suite
uv run pytest -m integration  # integration tests only
uv run ruff check .           # lint
uv run mypy agent_assembly    # type-check
```

See [CONTRIBUTING.md](https://github.com/ai-agent-assembly/python-sdk/blob/master/CONTRIBUTING.md)
for the full workflow.
