---
name: sdk-only-release
description: Publish an SDK-only agent-assembly Python release (no agent-assembly core bump) via release-python.yml workflow_dispatch.
---

# SKILL.md — sdk-only-release

> **Repo**: `python-sdk`. This skill drives the `release-python.yml` workflow
> in `workflow_dispatch` mode to publish a Python-only PyPI release without
> cutting a new `agent-assembly` core tag. For the node-sdk counterpart see
> the sibling skill in that repository.

## Purpose

Ship a Python-only `agent-assembly` release to PyPI in cases where the bundled
`aasm` sidecar binary is healthy and only the Python surface needs to change.
Valid drivers include: bug fix, dependency bump, refactor, doc rebuild, or a
small SDK-only feature. The skill is **not** hotfix-specific — the rename from
`sdk-only-hotfix` is deliberate.

## When to use

Use this skill when the `agent-assembly` Python SDK needs a republish for **any**
reason that does not require cutting a new `agent-assembly` core tag — a new
SDK feature, a refactor, a dependency bump, a bug fix, a documentation rebuild,
or a pre-release iteration of the Python surface. The skill is deliberately
broader than the original "hotfix-only" framing; SDK-only republishes are a
normal release path, not an emergency one.

## When NOT to use

- A new `agent-assembly` tag is being cut. The upstream `release.yml` workflow
  fires a `repository_dispatch` event at `python-sdk` automatically, which
  exercises the same `release-python.yml` workflow. Running this skill
  on top of that flow would double-publish to PyPI.
- The operator wants to bump the bundled `aasm` sidecar binary tarball source.
  That is a `binary_source_tag` change and can be combined with a same-or-new
  `pypi_version` if needed — but the intent is to refresh the binary, not the
  Python surface alone. Decide which axis is actually changing before invoking.

## Type

Command-style. Invoke explicitly when the operator decides to dispatch a
Python-only release. Do not invoke automatically from polling skills.

## How to use

Invoke `release-python.yml` via `workflow_dispatch` against `master`:

```bash
gh workflow run release-python.yml \
  --repo ai-agent-assembly/python-sdk \
  --ref master \
  -f pypi_version=<X> \
  -f binary_source_tag=<Y> \
  -f dry-run=true
```

The workflow takes three input axes:

- `pypi_version` — the PEP 440 version published on PyPI (e.g. `0.0.1a9.post1`).
- `binary_source_tag` — the `agent-assembly` core tag (e.g. `v0.0.1-alpha.9`)
  whose `aasm-*.tar.gz` Release assets are bundled into the wheels.
- `dry-run` — `true` builds wheels only, `false` performs a real publish.

### Critical conversion: SemVer-ish tag vs PEP 440

The `agent-assembly` core repo uses SemVer-ish tags like `v0.0.1-alpha.N`,
but PyPI requires PEP 440 (`0.0.1aN`). The `resolve` job in `release-python.yml`
performs the conversion via `tag_to_pep440` (AAASM-2853 / AAASM-2854). When
dispatching from `workflow_dispatch`, the operator **supplies the PEP 440
form directly** in `pypi_version` — the workflow does not re-derive it. Pick
the PEP 440 form (`0.0.1a9`, `0.0.1a9.post1`, …) up front.

### Trusted Publisher auth

The workflow authenticates to PyPI via Trusted Publisher (OIDC) — no API token
is needed and none should be supplied. The `pypa/gh-action-pypi-publish` step
in the workflow handles the OIDC handshake. If auth fails, the fix is on the
PyPI Trusted Publisher configuration, not the workflow.

## Inputs (3 axes with non-obvious coupling)

| Input | Purpose |
|---|---|
| `pypi_version` | The version published on PyPI (PEP 440, e.g. `0.0.1a8.post1`). |
| `binary_source_tag` | The `agent-assembly` tag whose `aasm-*.tar.gz` Release assets are bundled into each wheel at `agent_assembly/bin/aasm`. |
| `dry-run` | `true` builds wheels only and skips PyPI upload. `false` performs a real publish — `pypi_version` is then required. |

### Key conversion — agent-assembly tag vs PEP 440

The `agent-assembly` repo uses SemVer-ish tags (`v0.0.1-alpha.8`), but PyPI
requires PEP 440 (`0.0.1a8`). The `resolve` job in `release-python.yml`
converts between the two via `tag_to_pep440` (see AAASM-2853 / AAASM-2854).
When dispatching from `workflow_dispatch`, the operator supplies the PEP 440
form directly in `pypi_version`; the conversion is only used for
`repository_dispatch` payload paths.

The `resolve` job also enforces:

- `binary_source_tag` must match `v*.*.*` semver (alpha/beta/rc suffix allowed).
- `pypi_version` must match a strict PEP 440 regex — forms like `0.0.1a8.1` or
  `0.0.1-alpha.8.1` are **rejected**, only `.postN` / `.devN` / `aN`/`bN`/`rcN`.
- `dry-run=false` with empty `pypi_version` fails fast.

## Pre-conditions

Before dispatching, confirm:

1. `pypi_version` resolves to a **higher** PEP 440 version than the latest
   published `agent-assembly` on PyPI. Check with
   `pip index versions agent-assembly` or
   `curl -s https://pypi.org/pypi/agent-assembly/json | jq -r '.releases | keys[]'`.
2. `binary_source_tag` is an existing `agent-assembly` tag with published
   GitHub Release assets (`aasm-*.tar.gz` for all four target platforms).
   Verify with
   `gh release view <tag> --repo ai-agent-assembly/agent-assembly`.
3. The operator has run `dry-run=true` first and reviewed the resolve output
   plus the built wheel artifacts.
4. The branch / `--ref` being dispatched against is `master` (the workflow is
   designed to run on master).

## Executable plan

### Step 1 — Dry-run dispatch

```bash
gh workflow run release-python.yml \
  --repo ai-agent-assembly/python-sdk \
  --ref master \
  -f pypi_version=0.0.1a8.post1 \
  -f binary_source_tag=v0.0.1-alpha.8 \
  -f dry-run=true
```

### Step 2 — Watch the run, surface the resolve output

```bash
gh run list --repo ai-agent-assembly/python-sdk --workflow release-python.yml --limit 1
gh run watch <run-id> --repo ai-agent-assembly/python-sdk
gh run view <run-id> --repo ai-agent-assembly/python-sdk --job <resolve-job-id> --log
```

In the `resolve` job log, confirm the line:

```
Resolved binary_source_tag=v0.0.1-alpha.8 pypi_version=0.0.1a8.post1 dry_run=true
```

This is the single source of truth for the SemVer-ish-tag → PEP 440 mapping
that the rest of the workflow consumes. If the conversion looks wrong, stop
and re-dispatch with the corrected inputs — do **not** edit the workflow.

### Step 3 — Re-dispatch with `dry-run=false`

Only after the dry-run is green and the resolve output is correct:

```bash
gh workflow run release-python.yml \
  --repo ai-agent-assembly/python-sdk \
  --ref master \
  -f pypi_version=0.0.1a8.post1 \
  -f binary_source_tag=v0.0.1-alpha.8 \
  -f dry-run=false
```

### Step 4 — Verify the PyPI publish

```bash
pip index versions agent-assembly
# or
curl -s https://pypi.org/pypi/agent-assembly/0.0.1a8.post1/json | jq '.info.version,.urls[].filename'
```

Confirm:

- The new version appears in `pip index versions`.
- All four wheels plus the sdist are listed under `.urls[].filename`.
- Filenames follow the cp312 ABI tag (see "Known quirks" below).

## Worked example

A concrete end-to-end run, showing the PEP 440 input form and the dry-run gate.

**Scenario.** Operator decides PyPI needs `agent-assembly==0.0.1a9.post1` — a
post-release of the alpha-9 Python surface with no change to the bundled
`aasm` binary. The binary tarballs already exist at `v0.0.1-alpha.9` from the
prior coordinated release.

**Dispatch (dry-run first).**

```bash
gh workflow run release-python.yml \
  --repo ai-agent-assembly/python-sdk \
  --ref master \
  -f pypi_version=0.0.1a9.post1 \
  -f binary_source_tag=v0.0.1-alpha.9 \
  -f dry-run=true
```

**`resolve` job output.** The job log confirms:

```
Resolved binary_source_tag=v0.0.1-alpha.9 pypi_version=0.0.1a9.post1 dry_run=true
```

and the strict PEP 440 regex accepts `0.0.1a9.post1`. The job also confirms
that `0.0.1a9.post1` sorts **higher** than the currently-latest `0.0.1a9` on
PyPI (PEP 440 ordering: `aN.postM > aN`).

**Wheel build.** The matrix produces the five expected artifacts:

- `agent_assembly-0.0.1a9.post1-cp312-cp312-macosx_11_0_arm64.whl`
- `agent_assembly-0.0.1a9.post1-cp312-cp312-macosx_10_12_x86_64.whl`
- `agent_assembly-0.0.1a9.post1-cp312-cp312-manylinux_2_17_aarch64.manylinux2014_aarch64.whl`
- `agent_assembly-0.0.1a9.post1-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl`
- `agent_assembly-0.0.1a9.post1.tar.gz` (sdist)

Dry-run completes green; operator downloads the wheel artifacts, inspects
filenames + sizes, and authorises the real publish.

**Real publish.** Re-dispatch with `dry-run=false`:

```bash
gh workflow run release-python.yml \
  --repo ai-agent-assembly/python-sdk \
  --ref master \
  -f pypi_version=0.0.1a9.post1 \
  -f binary_source_tag=v0.0.1-alpha.9 \
  -f dry-run=false
```

Trusted Publisher auths via OIDC; the upload succeeds. Verification:

```bash
pip index versions agent-assembly
# agent-assembly (0.0.1a9.post1)
#   Available versions: 0.0.1a9.post1, 0.0.1a9, 0.0.1a8.post1, 0.0.1a8, ...
```

confirms `0.0.1a9.post1` is the latest.

**Docs cascade.** The `Publish release tag for docs` job at the end of
`release-python.yml` **did not fire** — this is correct. That job is gated
on `repository_dispatch` (AAASM-2868), and this run was a
`workflow_dispatch`. If a documentation refresh is needed it must be
dispatched separately against the docs pipeline.

## Post-conditions

- Run `pip install agent-assembly==<pypi_version>` in a clean venv and import
  the package to confirm the bundled `aasm` binary is present at
  `agent_assembly/bin/aasm` and executes.
- **Yanked-but-higher uploads**: PyPI does not skip yanked versions for
  default `pip install` resolution. If a higher version (e.g. `0.0.2`) has
  been yanked, the operator should confirm `pip install agent-assembly`
  picks the new release rather than the yanked one. Check with
  `pip install agent-assembly==<pypi_version>` first (explicit pin always
  wins), then a bare `pip install agent-assembly --dry-run`.
- Record the published `pypi_version` and `binary_source_tag` pair in the
  release notes for traceability — the wheel bundles the **unchanged**
  `aasm` binary from `binary_source_tag`, byte-for-byte.

## What's expected when done

Once the publish job is green, the following observable end-state must hold:

- PyPI shows `agent-assembly==<pypi_version>` as the newest **non-yanked**
  version. Verify with:

  ```bash
  curl -s "https://pypi.org/pypi/agent-assembly/<pypi_version>/json" \
    | jq '.info.version'
  ```

  which must return `"<pypi_version>"`.

- `pip install agent-assembly` in a clean venv resolves to `<pypi_version>` —
  not a yanked-higher-version shadow. Sanity check with:

  ```bash
  pip install agent-assembly --dry-run
  ```

  This is the cross-check for the "yanked-but-higher" gotcha already noted in
  Post-conditions: PyPI does not skip yanked versions during default
  resolution if they sort highest, so this dry-run is non-trivial.

- The `Publish release tag for docs` job at the end of `release-python.yml`
  **did not fire** — this is intentional under `workflow_dispatch` (gated on
  `repository_dispatch` per AAASM-2868). The release-channel docs snapshot is
  out of scope for this skill; if a refresh is needed, dispatch the docs
  pipeline separately.

## Known quirks (encoded so the operator does not relearn them)

- **cp312-only wheels**. The wheels are built for CPython 3.12 only; there is
  no `abi3` build. Future Python minor releases (3.13, 3.14, …) require a
  republish from the python-sdk workflow with an updated target. Remind the
  operator that the published artifacts work **only on Python 3.12** until
  that republish happens.
- **PyPI Trusted Publisher**. The workflow authenticates via PyPI's Trusted
  Publisher integration — no API token is needed and no token should be
  added. If publish fails on auth, the fix is on the PyPI side (the Trusted
  Publisher configuration), not in the workflow.
- **`workflow_dispatch` skips docs**. The `Publish release tag for docs` job
  at the end of `release-python.yml` is gated on the `repository_dispatch`
  event source (AAASM-2868 gate, landed in PR #88; runbook reference
  AAASM-2869). A `workflow_dispatch` SDK-only release will **not** push a
  release-channel docs snapshot. If docs need to be cut, that is a separate
  dispatch against the docs pipeline, not this workflow.
- **No `publish_mode` input**. Unlike node-sdk's workflow, python-sdk emits a
  single artifact set (sdist + four wheels) and has no `main-only` half-step.
  The SDK-only nature of the release is expressed entirely by the
  `pypi_version` (a `.postN` suffix on the parent tag) and by reusing the
  previous release's `binary_source_tag`.
- **PEP 440 vs SemVer**. Do **not** invent forms like `0.0.1a8.1` or
  `0.0.1-alpha.8.1` — the `resolve` job's regex will reject them. Use
  `0.0.1a8.post1`, `0.0.1a8.post2`, … and reserve clean `aN` slots for
  coordinated agent-assembly releases.

## Do Not Assume

- Do not assume the previous `binary_source_tag` is still the right one —
  re-confirm via `gh release view` that the assets exist before dispatching.
- Do not assume `dry-run=true` exercises the publish path; it intentionally
  skips PyPI upload. Trust must be earned by the dry-run wheel artifacts
  plus the second `dry-run=false` dispatch.
- Do not assume a failed dry-run is safe to retry without investigation —
  the `resolve` job's strict validation (semver tag, PEP 440 version,
  non-empty version on real publish) usually points at the dispatch input.

## Validation Guidance

- After the dry-run run completes, download the built wheel artifacts from
  the run page and inspect their filenames + sizes locally before
  authorising the real publish.
- After the real publish, run `pip install agent-assembly==<pypi_version>`
  in a fresh venv and execute `python -c "import agent_assembly; print(agent_assembly.__version__)"`
  plus `agent_assembly/bin/aasm --version` (path inside the installed
  package) to confirm both halves of the wheel are correct.

## Cross-references

- `docs/release/RUNBOOK.md` § "SDK-only hotfix mode" — operator runbook for
  the same workflow path, including the "when NOT to use SDK-only mode"
  guidance, the PEP 440 vs node-sdk semver comparison, and the
  documentation-snapshot gate details.
- Sibling skill `sdk-only-release` in `node-sdk` — symmetric counterpart
  with different artifact-set mechanics (five npm packages vs one PyPI
  artifact set) and a `publish_mode=main-only` half-step that does not
  exist here.
