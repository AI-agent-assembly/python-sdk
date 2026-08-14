# CLAUDE.md — python-sdk

Guidance for Claude Code (and humans) working in this repository. This file holds
**repo-specific** context only; universal engineering policy lives in the global
config. When a fact here duplicates `CONTRIBUTING.md`, `pyproject.toml`, or
`.github/workflows/ci.yaml`, treat those as the source of truth and update them, not
just this file.

## What this repo is

The **Python SDK** for AI Agent Assembly — the product that enforces governance on
AI agents. It is two layers under one PyPI wheel (`agent-assembly`):

1. A **pure-Python client** (`agent_assembly/`) — framework adapters, the gateway
   client, `init_assembly()`, exception hierarchy, and Pydantic models. Pure-Python
   users need no Rust toolchain.
2. A **thin PyO3 native shim** (`native/aa-ffi-python/`) — a `cdylib` exposed as
   `agent_assembly._core`. It delegates to the **`aa-sdk-client`** crate, pinned by
   **git SHA** from the `ai-agent-assembly/agent-assembly` monorepo (alongside
   `aa-core` and `aa-proto` — all three must share one rev so cargo resolves a single
   copy; see the pin comment in `native/aa-ffi-python/Cargo.toml`). The native fast
   path is optional, selected at runtime, and only required for sub-millisecond
   policy checks.

This repo is **not** the protocol's source of truth. The wire types, policy
semantics, and the `aa-*` crates this SDK binds to live in the **`agent-assembly`
monorepo**; this SDK consumes them.

## Where this sits in the three-layer interception model

The product enforces governance through three independently-deployable layers,
ordered by latency cost (lowest first) and detection authority (highest first):

1. **SDK layer (in-process)** — *this repo*. The SDK applies pre-execution allow/deny
   on tool calls via the native shim over `aa-sdk-client`. Fastest path; requires SDK
   adoption. It hands audit events to the runtime **only over a connected runtime**:
   the adapters offer a governed outcome to an audit hook, and
   `RuntimeQueryInterceptor` writes it to the native event channel. Two limits are
   load-bearing and must not be dropped when describing this: the send is
   unacknowledged, so a handoff is **not** evidence and never ADR 0033 §6
   *Observed* — AAASM-5783 is open on the downstream half and must land before
   that changes; and only `google_adk`, `pydantic_ai` and `openai_agents` record on the
   **denied** path — the other eight governed adapters return or raise first. With no
   reachable runtime nothing is recorded at all (AAASM-5750). Never describe this
   layer as producing an audit trail.
2. **Sidecar proxy (`aa-proxy`)** — MitM of outbound HTTPS; enforces network-egress
   policy with no code changes. (Lives in the monorepo.)
3. **eBPF (`aa-ebpf*`)** — kernel uprobes; catches everything, including bypass
   attempts. Linux-only. (Lives in the monorepo.)

## Build, test, lint

Python ≥ 3.12 (CI matrix: 3.12, 3.13, 3.14). `uv` manages the venv; `hatchling`
packages the pure-Python wheel; `maturin` builds the native extension. See
`CONTRIBUTING.md` for the full contributor flow. Common commands:

```bash
uv sync                                # create .venv + install runtime + dev deps
.venv/bin/python -m pytest test/       # full suite
.venv/bin/python -m pytest test/unit/cli/test_loader.py            # one file
.venv/bin/python -m pytest test/unit/cli/test_loader.py::TestLoadAdapterClass  # one class
.venv/bin/ruff check .
.venv/bin/ruff format .                # formatter gate (see .pre-commit-config.yaml)
.venv/bin/mypy agent_assembly          # strict; type-check the package, not test/
.venv/bin/pre-commit run --all-files
```

- The CLI entry point is `aasm = "agent_assembly.cli.main:main"`.
- Native fast path (optional, for the PyO3 shim):
  `uv tool run maturin develop --manifest-path native/aa-ffi-python/Cargo.toml`.

## Config surface

`init_assembly()` (`agent_assembly/core/assembly.py`) takes two orthogonal axes:

- **`mode`** (interception layer): `auto` (default) · `ebpf` · `proxy` · `sdk-only`.
- **`enforcement_mode`** (governance posture): `enforce` (default — deny blocks,
  redact strips secrets) · `observe` (dry-run; gateway records what *would* happen) ·
  `disabled` (policy skipped entirely — hermetic test only).

The gateway URL/key resolver (`agent_assembly/core/gateway_resolver.py`) resolves in
this order: explicit args → env (`AAASM_GATEWAY_URL` / `AAASM_API_KEY`) →
`~/.aasm/config.yaml` (optional) → probe local default `http://localhost:7391`
(auto-start if absent).

**Import public types from `agent_assembly.types`** — a top-level
`from agent_assembly import <Type>` import fails mypy strict.

## Conventions (see `CONTRIBUTING.md` — don't duplicate)

- **Commits:** `<emoji> (<scope>): <imperative summary>` (gitmoji.dev). One logical
  unit per commit; bisectable. Utils/mocks/tests are separate preceding commits.
- **Branch:** `<release-or-phase>/<ticket>/<type>/<short_summary>`
  (e.g. `v0.0.1/AAASM-42/feat/add_langchain_adapter`).
- **PR title:** `[<ticket>] <emoji> (<scope>): <summary>`; base branch **always
  `main`**; body follows `.github/pull_request_template.md`; ≥1 Pioneer-team
  approval.

## Repo-specific gotchas

- **The `LICENSE` is MIT BY DESIGN.** The rest of the org is Apache-2.0; the owner
  has confirmed MIT for this SDK twice. The `LICENSE`, the PyPI classifier, and the
  README badge are all intentionally MIT — **do not "fix" it** to Apache.
- **Push remote is `remote`** (→ `ai-agent-assembly/python-sdk`, canonical), not
  `origin` (a personal fork). Scope changes against `remote/main`, which is often
  ahead of a fork checkout. The "This repository moved"
  (old-uppercase→`ai-agent-assembly`) redirect notice on push is harmless.
- **Docs-only PRs run NO CI.** `ci.yaml`'s `pull_request.paths` allow-list covers
  only `agent_assembly/**/*.py`, `test/**/*.py`, and specific config files — it
  **excludes** `docs/**`, `*.md`, and `examples/**`. A docs-only PR with no CI is
  *review-required*, not a failure. (`pre-commit` also excludes `.github/` and
  `docs/`.) Exception: `README.md` / `pyproject.toml` edits trigger the
  `readme-version-check.yml` gate below.
- **README version literal is SoT-gated.** The `aasm --version` sample output in
  `README.md` must equal the `pyproject.toml` version anchor (`[project].version`) —
  the single source of truth per [ADR 0013](https://github.com/ai-agent-assembly/agent-assembly/blob/master/docs/src/adr/0013-version-metadata-source-of-truth-and-drift-gate.md).
  `scripts/check_readme_version.py --check` (blocking CI: `readme-version-check.yml`)
  fails the build on drift. Don't retype the README literal on a bump without
  matching the anchor.
- **macOS native build:** building the PyO3 `cdylib` via a plain `cargo build`
  link-fails (unresolved Python symbols). Use **maturin**, or
  `cargo rustc -- -Clink-arg=-undefined -Clink-arg=dynamic_lookup`.
- **Native shim pin:** `aa-core` / `aa-proto` / `aa-sdk-client` must stay on one
  shared git SHA. Bumping the pin coordinates with the monorepo — don't bump one
  without the others.
- **Never `--no-verify`; never force-push.** If a fresh worktree's hooks fail for
  lack of `.venv`/`node_modules`, install or symlink — don't bypass.

## Project policy

- **JIRA:** project AAASM; set the native **Components** field to
  `ai-agent-assembly/python-sdk`; Team (`customfield_10001`) = Pioneer.
  Epic → Story → Subtask (one Subtask ≈ one commit) + a `Verify …` subtask per Story.
- **Self-hosted deployment is out of scope** product-wide — don't propose
  Helm/Terraform/air-gapped/migration work even if the spec mentions it.
- **The Protocol Specification stays in the `agent-assembly` monorepo** — this SDK
  consumes the protocol, it does not define it.

## Documentation conventions — document the WHY, not the WHAT

Comments and docstrings exist to capture intent that the code cannot: rationale,
constraints, invariants, and non-obvious decisions. Restating what the code already
says is noise that rots out of sync — avoid it.

- **Module docstrings (`"""..."""` at top of file):** yes — the module's role, key
  invariants, and where it sits in the architecture (e.g. which interception layer or
  adapter family it serves).
- **Public API (Google-style docstrings on `public` functions/classes):** yes — the
  contract: `Args`/`Returns`/`Raises`, units, side effects, and any
  async/threading/`mode`-dependent behavior. Especially the surprising ones (e.g.
  *why* `mode="auto"` falls back, *why* a value resolves the way it does).
- **Inline `#` why-comments:** for workarounds, perf-sensitive code, security
  rationale, and dependency pins. The `pyproject.toml` and `Cargo.toml` pin comments
  are the gold standard — *why* a version is held, not just that it is.
- **Skip:** private trivial helpers, getters, type-restating, and anything a reader
  infers from the signature or type hints. No per-variable comments.
- **Big architectural decisions → ADRs**, not scattered docstrings. Link code to the
  ADR (the native shim's git-SHA pin references ADR 0002 / AAASM-2559). Reference
  design specs rather than re-describing them inline.

> Net: a new contributor (human or LLM) should be able to read a module's docstring
> and a public function's docstring and understand *why it is the way it is* without
> reverse-engineering it. If a comment only says *what*, delete it.
