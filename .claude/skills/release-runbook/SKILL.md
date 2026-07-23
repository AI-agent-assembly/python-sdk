---
name: release-runbook
description: End-to-end release runbook for the python-sdk repo. Explains how a Python `agent-assembly` release reaches PyPI — the normal coordinated path driven by an upstream `agent-assembly` core tag (repository_dispatch → build native wheels + publish), how to validate the published package, and the SDK-only hotfix path via `release-python.yml` `workflow_dispatch`. Use when an operator needs to understand or drive a python-sdk release, or to decide between the coordinated and SDK-only paths.
---

# release-runbook

Operator-facing runbook for shipping the `agent-assembly` Python distribution to
PyPI from the `python-sdk` repo. This SKILL.md is the overview; the executable
`workflow_dispatch` mechanics for the SDK-only path live in the sibling
[`sdk-only-release`](../sdk-only-release/SKILL.md) skill.

> **Repo**: `python-sdk`. Canonical remote is `remote`
> (`ai-agent-assembly/python-sdk`), **not** `origin` (the personal fork).
> All release machinery lives in `.github/workflows/release-python.yml`.

## The single source of release truth: `release-python.yml`

There is exactly one release workflow — `.github/workflows/release-python.yml` —
and it serves **both** the normal path and the hotfix path. Which path runs is
decided entirely by its trigger:

| Trigger | Path | `dry_run` | Who fires it |
|---|---|---|---|
| `repository_dispatch` (type `agent-assembly-release-published`) | Normal coordinated release | always `false` (real publish) | `agent-assembly`'s `notify-downstream` job, after an upstream core tag is released |
| `workflow_dispatch` | SDK-only release / hotfix | operator-supplied (defaults `false`) | the operator, manually |

The first job, `resolve`, normalises both triggers into a single set of outputs
(`binary_source_tag`, `pypi_version`, `dry_run`, `release_tag`) that every
downstream build/publish job consumes. Everything after `resolve` is
path-agnostic — the only difference between the two paths is how those four
values are produced.

## Why this is coupled to an `agent-assembly` core tag

The Python wheel is **not** pure Python. It bundles two things from a specific
`agent-assembly` core release:

1. **The `aasm` sidecar binary** — each per-platform build job downloads
   `aasm-<target>.tar.gz` from the `ai-agent-assembly/agent-assembly` GitHub
   Release identified by `binary_source_tag`, and stages it at
   `agent_assembly/bin/aasm` inside the wheel (matching `runtime.py`'s
   `WHEEL_BUNDLED_BIN` search path).
2. **The compiled `aa-ffi-python` PyO3 extension** — maturin compiles it from
   source against the git-SHA `rev` pins in `native/aa-ffi-python/Cargo.toml`
   (`aa-core`, `aa-proto`, `aa-sdk-client`).

Because of this, **a Python release is always tied to a core tag**
(`binary_source_tag`). The whole point of the coordinated path is to keep the
bundled binary and the compiled FFI in lockstep with the core release the user
expects.

### The one-cycle source-pin lag (`pin-ffi-to-tag.sh`)

`master`'s `Cargo.toml` FFI pins lag the latest core release by one cycle —
they are only bumped to the just-released commit by a *separate* post-publish
bump PR (`bot/aa-ffi-pin-<tag>`). So if maturin built straight off `master`'s
pins, the published wheel would compile against the **previous** core release,
mismatching the binary it bundles.

To prevent this, every build job runs `.github/scripts/pin-ffi-to-tag.sh
<binary_source_tag>` *before* maturin: it resolves the tag to a 40-hex commit
SHA and rewrites the `rev = "…"` pins in the CI working tree. This is an
**ephemeral CI edit, never committed back** — `master` stays synced separately
by the bump PR. (AAASM-2959.)

### Why the `sync-version` composite action exists

`master`'s `pyproject.toml` / `agent_assembly/__init__.py` version also lags the
release. If maturin read the checked-in version, the wheel filename would
collide with an already-published PyPI version and the upload would be rejected
(the alpha-4 incident, AAASM-2459).

`.github/actions/sync-version` rewrites the version in both files to the
resolve-job's `pypi_version` **before** maturin reads `pyproject.toml`. When
`pypi_version` is empty (a dry-run), it is a deliberate no-op and the wheel
keeps the master version — useful for build-only smoke tests.

### The SemVer ↔ PEP 440 conversion

`agent-assembly` tags are SemVer-ish (`v0.0.1-alpha.8`); PyPI requires PEP 440
(`0.0.1a8`). Two sourceable scripts are the single source of truth for the
conversion, shared with their fixture suites (run by
`release-python-conversion-test.yml`):

- `.github/scripts/tag-to-pep440.sh` — `v0.0.1-alpha.8` → `0.0.1a8`
  (used on the `repository_dispatch` path to derive `pypi_version` from the tag).
- `.github/scripts/pep440-to-tag.sh` — `0.0.1a8` → `v0.0.1-alpha.8`
  (used to derive the python-sdk's own Release tag from `pypi_version`;
  `.post`/`.dev` republish forms produce no tag, so they get no Release).

## Path A — normal coordinated release (the default)

This is the path you almost never trigger by hand; it is fired automatically.

1. An operator cuts an `agent-assembly` core tag (see the `release-tag-cut`
   skill in the `agent-assembly` repo). Its `release.yml` builds and publishes
   the core, uploads the `aasm-*` assets, then its `notify-downstream` job sends
   a `repository_dispatch` (`agent-assembly-release-published`) to `python-sdk`
   carrying `client_payload.release_tag` (e.g. `v0.0.1-alpha.8`).
2. `release-python.yml` `resolve` runs: `binary_source_tag = release_tag`,
   `pypi_version = tag_to_pep440(release_tag)`, `dry_run = false`,
   `release_tag = release_tag` (verbatim — used to cut python-sdk's own Release).
3. The five build jobs (sdist + 4 platform wheels: linux x86_64/aarch64, macOS
   arm64/x86_64) each stage the `aasm` binary, run `pin-ffi-to-tag.sh`, run
   `sync-version`, then maturin-build.
4. `publish` downloads all artifacts and uploads to PyPI via the
   `pypa/gh-action-pypi-publish` **Trusted Publisher (OIDC)** — there is no
   stored API token (`id-token: write`, environment `pypi`).
5. `create-github-release` cuts python-sdk's own GitHub Release at
   `release_tag` (so the repo's release line + README badge track PyPI; pre-1.0
   tags get `--prerelease`). `publish-release-tag` writes `release-tag.txt` so
   the docs workflow can label the frozen docs snapshot (AAASM-2750).

**Operator action on this path is essentially none** — your job is to make the
upstream core release happen and then *validate* the result.

## Sync docs version refs + example pins (before publish)

The workflow's `sync-version` rewrites `pyproject.toml` / `__init__.py` **in CI
only** (see above), so the *published* wheel is always correct regardless of what
`master` says. But the checked-in repo and the docs site still advertise the old
version — left alone they rot, lying to readers and badges. Before the publish
fires (or in a follow-up PR on the same cycle), bring the repo in sync:

1. **Bump the checked-in version file** to match the run's `pypi_version` (the
   `repository_dispatch` payload's tag converted via `tag-to-pep440.sh`, or the
   `workflow_dispatch` input). Edit `version` in `pyproject.toml` **and**
   `__version__` in `agent_assembly/__init__.py`, then regenerate the lock:
   `uv lock`. This is for honesty + the README badge — the wheel version itself
   comes from CI's `sync-version`, not from these files. **In the same
   version-bump prep commit, bump `sonar.projectVersion` in
   `sonar-project.properties`** to the new version. The static value is the
   source-of-truth / local-scan fallback; CI overrides it dynamically at scan
   time (the SonarCloud Scan job derives it from `pyproject.toml`), so drift
   never breaks CI — but the static value must still track the release. This is
   the step rc.1 prep PRs missed and rc.2 had to fix by hand; it mirrors the
   core's `release-tag-cut` automation (AAASM-3819).
2. **Sweep the docs site for pinned versions** —
   `git grep -nE 'agent-assembly\s*[<>=]' docs/` — and bump any *current-version*
   dependency pin to the new version. (Exact-version `==` callouts in
   `docs/compatibility/` and `docs/index.md` count.)
3. **New-feature adapter examples are forward-reference pins — the easily-missed
   trap.** An example for an adapter added *after* the last published tag cannot
   pin the last published version: that version does not contain the adapter. It
   must pin `agent-assembly>=<new version>`. Verify per adapter against the last
   published tag:

   ```bash
   git cat-file -e <last-published-tag>:agent_assembly/adapters/<name>/__init__.py
   ```

   If that **errors** (the adapter is absent from the published tag), the
   example's pin **must** be the new version, not the last one. If it succeeds,
   the adapter shipped already and its existing lower pin is valid — leave it.
   The b5 wave found four wrong: `agno` was pinned `>=…b4` and
   `haystack` / `microsoft-agent-framework` / `smolagents` were pinned `>=…b2`,
   yet all four adapters only ship in b5, so every one had to move to `>=…b5`.
4. **Add the new release-notes section.** Prepend a new `## <version>` heading at
   the **top** of the version list in `docs/compatibility/release-notes.md`
   (immediately above the most recent existing entry), summarizing this release —
   the channel promotion and the headline changes since the last published tag.
   Use the hyphenated tag form of the version (e.g. `## 0.0.1-rc.1`) to match the
   existing headers. Derive the highlights from the delta
   (`git log --oneline <last-tag>..HEAD` / the merged PRs since the last tag); do
   not invent changes. This is the one *additive* edit to the file — it is
   distinct from, and must not be conflated with, the don't-rewrite-history rule
   below.
5. **Leave the history alone.** Do **not** rewrite `CHANGELOG` /
   `docs/compatibility/release-notes.md` past entries, and do **not** touch the
   auto-managed Docusaurus docs snapshot (`publish-release-tag` labels it — see
   above). You are syncing *current* pins and adding the one new section above —
   not editing the historical record.

(The `agent-assembly` core `release-docs-sync` skill is the canonical, full
version-sweep procedure across every channel; this section is the python slice.)

## Path B — SDK-only release / hotfix (`workflow_dispatch`)

Use this when the Python surface needs a republish but the bundled `aasm` binary
and core are unchanged (a bug fix, dependency bump, refactor, doc rebuild, or a
small SDK-only feature). It does **not** cut an `agent-assembly` core tag.

Inputs to `release-python.yml` `workflow_dispatch`:

| Input | Meaning | Notes |
|---|---|---|
| `pypi_version` | PEP 440 version published to PyPI (e.g. `0.0.1a9.post1`) | Required when `dry-run` is false; supplied **directly in PEP 440 form** (you do the conversion, not the workflow) |
| `binary_source_tag` | `agent-assembly` core tag whose `aasm-*` assets to bundle | Optional; **defaults to the latest `agent-assembly` Release** if omitted |
| `dry-run` | `true` = build wheels only, skip PyPI upload | Defaults `false` (AAASM-2856) |

Always **dry-run first**, confirm the resolve-job's
`Resolved binary_source_tag=… pypi_version=… dry_run=…` line, then re-dispatch
with `dry-run=false`. Full executable mechanics, the strict PEP 440 regex, the
release-coordination SOP (Case A: wait for the core release + FFI-pin bump PR
before publishing; the 2026-06-15 double-publish incident, AAASM-3007), and a
worked `0.0.1a9.post1` example live in the
[`sdk-only-release`](../sdk-only-release/SKILL.md) skill. Prefer that skill to
drive an actual SDK-only dispatch.

## Validating the published package

After either path's run completes:

1. **Resolve job output** — confirm `Resolved binary_source_tag=… pypi_version=…
   dry_run=false …` matches what you expected (this is the source of truth for
   the tag → version mapping).
2. **PyPI** — `pip index versions agent-assembly` shows the new version with all
   four platform wheels + the sdist and `cp312` ABI tags.
3. **Install smoke test** — in a clean venv, `pip install agent-assembly==<X>`,
   then confirm the bundled sidecar runs: `python -c "import agent_assembly"`
   and `aasm --version` resolves to the staged binary.
4. **Bundled-binary provenance** — the wheel's `agent_assembly/bin/aasm` came
   from `binary_source_tag`'s release; if the SDK version label implies a
   specific core fix, the bundled binary must carry it (the 2026-06-15 lesson).
5. **GitHub Release + docs** — on a real SemVer publish, python-sdk's own
   Release exists at `release_tag` and the docs snapshot is labelled.

(For a full cross-channel matrix of an `agent-assembly` release, the
`release-validate-channels` skill in the `agent-assembly` repo is the
authoritative checker.)

## Pre-conditions

- Canonical remote is `remote` (not `origin`); dispatch against `--ref main`.
- For Path B, `pypi_version` must be a **higher** PEP 440 version than the latest
  on PyPI, and `binary_source_tag` must be an existing `agent-assembly` tag with
  published `aasm-*` assets for all four platforms.
- If `agent-assembly` is releasing the same cycle, do **not** SDK-publish first —
  follow the Case A ordering in `sdk-only-release` (wait for the core tag + the
  `bot/aa-ffi-pin-<tag>` bump PR to merge).

## What is auto-handled (do NOT run by hand)

- `maturin build` / sdist construction (incl. the `aasm` download) — in the
  build matrix.
- `twine upload` — replaced by Trusted-Publisher OIDC; there is no token.
- The FFI pin rewrite (`pin-ffi-to-tag.sh`) — ephemeral CI edit; never commit it.
- The version rewrite (`sync-version`) — happens in CI before maturin.
- Cutting python-sdk's GitHub Release / docs snapshot — `create-github-release`
  + `publish-release-tag`.
- Cutting an `agent-assembly` core tag for an SDK-only change — that triggers the
  full coordinated pipeline and double-publishes.
- **The CI-side `sonar.projectVersion` override** — the SonarCloud Scan job in
  `rw_run_all_test_and_record.yaml` derives the version from `pyproject.toml`'s
  `version` at scan time and passes it via the scanner `args`, so the SonarCloud
  quality gate always tracks the current release regardless of the literal in
  `sonar-project.properties`. You therefore do not need a CI-driven bump — but
  you **do** still bump the static `sonar.projectVersion` literal as part of the
  version-bump prep commit (see "Sync docs version refs + example pins" step 1
  above): it is the source-of-truth / local-scan fallback and must track the
  release, never sitting at `0.0.0` (which leaves the gate "Not computed",
  AAASM-3815). This mirrors the `agent-assembly` monorepo, where the literal is
  bumped statically (AAASM-3819).

## What this runbook does not cover

- The upstream `agent-assembly` tag cut itself → `release-tag-cut` skill in the
  `agent-assembly` repo.
- Cross-channel validation of a full coordinated release →
  `release-validate-channels` skill in the `agent-assembly` repo.
- Yanking a bad PyPI version → do it in the PyPI web UI after the fact.

## Cross-references

- `agent-assembly` core's `release-docs-sync` skill — the canonical full
  version-sweep + forward-ref-pin procedure across all channels; the
  "Sync docs version refs + example pins" section above is the python slice of it.
- [`sdk-only-release`](../sdk-only-release/SKILL.md) — executable `workflow_dispatch`
  driver for Path B (inputs, dry-run gate, PEP 440 example, coordination SOP).
- `docs/release/RUNBOOK.md` (if present) — operator prose for the same paths.
- node-sdk's `sdk-only-release` — symmetric counterpart (five npm packages +
  a `publish_mode` half-step that does not exist for Python's single artifact set).
