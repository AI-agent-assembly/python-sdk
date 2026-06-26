---
name: sdk-only-release
description: Publish an SDK-only agent-assembly Python release via the release-python.yml workflow_dispatch, without cutting a new agent-assembly core tag. Use when the Python SDK needs a republish that does not change the core binaries — a feature, refactor, dependency bump, bug fix, or doc rebuild — supplying pypi_version (PEP 440), binary_source_tag, and a dry-run-first dispatch; the resolve job handles the SemVer-tag-to-PEP-440 conversion.
---

# SKILL.md — sdk-only-release

> **Repo**: `python-sdk`. This skill drives the `release-python.yml` workflow
> in `workflow_dispatch` mode to publish a Python-only PyPI release without
> cutting a new `agent-assembly` core tag. For the node-sdk counterpart see
> the sibling skill in that repository.

## Purpose

Ship a Python-only `agent-assembly` release to PyPI when the bundled `aasm`
sidecar binary is healthy and only the Python surface needs to change. Valid
drivers: bug fix, dependency bump, refactor, doc rebuild, or a small SDK-only
feature. The skill is **not** hotfix-specific — the rename from
`sdk-only-hotfix` is deliberate. Command-style; invoke explicitly, never from
polling skills.

## When to use

Use when the `agent-assembly` Python SDK needs a republish for **any** reason
that does not require cutting a new `agent-assembly` core tag — a new SDK
feature, refactor, dependency bump, bug fix, documentation rebuild, or a
pre-release iteration of the Python surface. SDK-only republishes are a normal
release path, not an emergency one.

## When NOT to use

- A new `agent-assembly` tag is being cut. The upstream `release.yml` fires a
  `repository_dispatch` at `python-sdk` automatically, exercising the same
  `release-python.yml`. Running this skill on top would double-publish to PyPI.
- The operator wants to bump the bundled `aasm` sidecar binary tarball source.
  That is a `binary_source_tag` change — decide which axis is actually changing
  before invoking.

## Release-coordination SOP — when agent-assembly is ALSO releasing

This is the canonical ordering rule operators MUST follow whenever `agent-assembly` is cutting a release in the same version cycle as this SDK. Codified after the 2026-06-15 incident (AAASM-3007).

### Case A — agent-assembly is ALSO releasing this version cycle

The SDK release MUST wait. Required order:

1. Cut the `agent-assembly` tag (e.g. `v0.0.1-beta.3`) and wait for its `Release` workflow to complete (build → publish → `notify-downstream`).
2. Wait for the auto-bump PR (`bot/aa-ffi-pin-<tag>`) to open on this repo (AAASM-2883 for node/python; AAASM-3006 extends the same fan-out to go-sdk).
3. Review + merge the auto-bump PR. This brings `master` in line with the `aa-sdk-client` SHA carried by the new agent-assembly tag.
4. ONLY THEN cut the SDK tag (matching version) — by tag-push OR `workflow_dispatch` — to fire this skill.

Do NOT pre-publish the SDK tag against the previous agent-assembly content. Doing so:

- Burns the version slot on the registry (npm / PyPI refuse re-publish).
- Means users installing that SDK version get content that does NOT carry the agent-assembly fix they expect.

### Case B — SDK-only release (no agent-assembly cut in this cycle)

This skill may be triggered freely via `workflow_dispatch`. No coordination required, because the existing `aa-sdk-client` SHA pin on `master` is already what we want to ship.

### Why this SOP exists (the 2026-06-15 incident)

On 2026-06-15 02:21 UTC, `@agent-assembly/sdk@0.0.1-beta.2` was published to npm via `workflow_dispatch` while `agent-assembly`'s latest release was still `v0.0.1-beta.1` (pre-AAASM-3000 IPC fix). The bundle on npm at version `0.0.1-beta.2` therefore does NOT carry the AAASM-3000 fix that users would reasonably expect from that version label. Same incident on PyPI at 02:22 UTC.

The fix is operator discipline (this SOP), not a workflow-code restriction — `workflow_dispatch` is kept open for legitimate Case B releases.

## How to use

Invoke `release-python.yml` via `workflow_dispatch` against `master`, three
input axes:

```bash
gh workflow run release-python.yml \
  --repo ai-agent-assembly/python-sdk \
  --ref master \
  -f pypi_version=<X> \
  -f binary_source_tag=<Y> \
  -f dry-run=true
```

- `pypi_version` — PEP 440 version published on PyPI (e.g. `0.0.1a9.post1`).
- `binary_source_tag` — the `agent-assembly` core tag (e.g. `v0.0.1-alpha.9`)
  whose `aasm-*.tar.gz` assets are bundled into the wheels.
- `dry-run` — `true` builds wheels only; `false` performs a real publish
  (`pypi_version` then required).

**PEP 440 conversion (brief).** `agent-assembly` uses SemVer-ish tags
(`v0.0.1-alpha.N`); PyPI requires PEP 440 (`0.0.1aN`). The `resolve` job
handles the conversion via `tag_to_pep440`. Under `workflow_dispatch` the
operator supplies the PEP 440 form **directly** in `pypi_version`. Full input
semantics, the strict regex, and Trusted-Publisher auth are in
[REFERENCE.md](REFERENCE.md).

## Pre-conditions

1. `pypi_version` resolves to a **higher** PEP 440 version than the latest
   published `agent-assembly` on PyPI
   (`pip index versions agent-assembly`).
2. `binary_source_tag` is an existing `agent-assembly` tag with published
   `aasm-*.tar.gz` assets for all four platforms
   (`gh release view <tag> --repo ai-agent-assembly/agent-assembly`).
3. The operator ran `dry-run=true` first and reviewed resolve output + wheels.
4. The `--ref` dispatched against is `master`.

## Executable plan

1. **Dry-run dispatch** — `gh workflow run release-python.yml … -f dry-run=true`.
2. **Watch the run, surface resolve output** — `gh run watch <run-id>`; confirm
   the `Resolved binary_source_tag=… pypi_version=… dry_run=true` line. This is
   the single source of truth for the tag → PEP 440 mapping. If it looks wrong,
   re-dispatch with corrected inputs — do **not** edit the workflow.
3. **Re-dispatch with `dry-run=false`** — only after the dry-run is green and
   the resolve output is correct.
4. **Verify the PyPI publish** — `pip index versions agent-assembly`; confirm
   the new version, all four wheels + sdist, and cp312 ABI tags.

A full annotated run (`0.0.1a9.post1`) is in [EXAMPLES.md](EXAMPLES.md).

## Do NOT manually run (auto-handled by the workflow)

Duplicate execution causes Trusted-Publisher conflicts, duplicate-tag errors,
or drifted wheels.

- **`python -m build` / `maturin build`** — wheel + sdist construction
  (including the `aasm` binary download) happens in the workflow matrix.
- **`twine upload`** — the workflow's `pypa/gh-action-pypi-publish` step uploads
  via OIDC Trusted Publisher credentials; there is no API token.
- **`git tag`** — SDK-only releases do not cut an `agent-assembly` core tag;
  pushing one triggers the full coordinated pipeline and double-publishes.
- **Docs version snapshot** — the `Publish release tag for docs` job is gated on
  `repository_dispatch` (AAASM-2868) and intentionally does **not** fire under
  `workflow_dispatch`. Dispatch the docs pipeline separately if needed.
- **Yanking lower versions** — this skill does not yank; do it in the PyPI web
  UI after the fact if required.
- **`sonar.projectVersion`** — the SonarCloud Scan job in
  `rw_run_all_test_and_record.yaml` derives it from `pyproject.toml`'s `version`
  at scan time, so the quality gate tracks the current release automatically. Do
  **not** hand-bump the `sonar.projectVersion` literal in
  `sonar-project.properties` per release — it is only the local-scan fallback and
  must stay off `0.0.0` (a literal `0.0.0` leaves the gate stuck at "Not
  computed"; AAASM-3815).

## Do Not Assume

- Do not assume the previous `binary_source_tag` is still right — re-confirm via
  `gh release view` that the assets exist before dispatching.
- Do not assume `dry-run=true` exercises the publish path; it skips PyPI upload.
- Do not assume a failed dry-run is safe to retry without investigation — the
  `resolve` job's strict validation usually points at the dispatch input.

## Detailed references

- Worked PEP 440 example (`0.0.1a9.post1`, dry-run gate, docs cascade) →
  [EXAMPLES.md](EXAMPLES.md)
- Input/conversion detail, strict PEP 440 regex, known quirks, and validation
  guidance → [REFERENCE.md](REFERENCE.md)

## Cross-references

- `docs/release/RUNBOOK.md` § "SDK-only hotfix mode" — operator runbook for the
  same workflow path.
- Sibling skill `sdk-only-release` in `node-sdk` — symmetric counterpart with
  five npm packages vs one PyPI artifact set and a `publish_mode=main-only`
  half-step that does not exist here.
