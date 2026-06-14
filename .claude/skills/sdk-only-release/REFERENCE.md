# REFERENCE.md — sdk-only-release

Detailed input semantics, the SemVer-ish-tag → PEP 440 conversion, known
quirks, and validation guidance for the `release-python.yml` SDK-only path.

## Contents

- [Inputs (3 axes with non-obvious coupling)](#inputs-3-axes-with-non-obvious-coupling)
- [Critical conversion — agent-assembly tag vs PEP 440](#critical-conversion--agent-assembly-tag-vs-pep-440)
- [Known quirks](#known-quirks)
- [Validation guidance](#validation-guidance)

## Inputs (3 axes with non-obvious coupling)

| Input | Purpose |
|---|---|
| `pypi_version` | The version published on PyPI (PEP 440, e.g. `0.0.1a8.post1`). |
| `binary_source_tag` | The `agent-assembly` tag whose `aasm-*.tar.gz` Release assets are bundled into each wheel at `agent_assembly/bin/aasm`. |
| `dry-run` | `true` builds wheels only and skips PyPI upload. `false` performs a real publish — `pypi_version` is then required. |

## Critical conversion — agent-assembly tag vs PEP 440

The `agent-assembly` core repo uses SemVer-ish tags like `v0.0.1-alpha.N`,
but PyPI requires PEP 440 (`0.0.1aN`). The `resolve` job in `release-python.yml`
performs the conversion via `tag_to_pep440` (AAASM-2853 / AAASM-2854). When
dispatching from `workflow_dispatch`, the operator **supplies the PEP 440
form directly** in `pypi_version` — the workflow does not re-derive it; the
conversion is only used for `repository_dispatch` payload paths. Pick the
PEP 440 form (`0.0.1a9`, `0.0.1a9.post1`, …) up front.

The `resolve` job also enforces:

- `binary_source_tag` must match `v*.*.*` semver (alpha/beta/rc suffix allowed).
- `pypi_version` must match a strict PEP 440 regex — forms like `0.0.1a8.1` or
  `0.0.1-alpha.8.1` are **rejected**, only `.postN` / `.devN` / `aN`/`bN`/`rcN`.
- `dry-run=false` with empty `pypi_version` fails fast.

### Trusted Publisher auth

The workflow authenticates to PyPI via Trusted Publisher (OIDC) — no API token
is needed and none should be supplied. The `pypa/gh-action-pypi-publish` step
in the workflow handles the OIDC handshake. If auth fails, the fix is on the
PyPI Trusted Publisher configuration, not the workflow.

## Known quirks

Encoded so the operator does not relearn them:

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
- **Yanked-but-higher uploads**. PyPI does not skip yanked versions for
  default `pip install` resolution. If a higher version (e.g. `0.0.2`) has
  been yanked, confirm `pip install agent-assembly` picks the new release
  rather than the yanked one — check `pip install agent-assembly==<pypi_version>`
  first (explicit pin always wins), then a bare `pip install agent-assembly --dry-run`.

## Validation guidance

- After the dry-run run completes, download the built wheel artifacts from
  the run page and inspect their filenames + sizes locally before
  authorising the real publish.
- After the real publish, run `pip install agent-assembly==<pypi_version>`
  in a fresh venv and execute `python -c "import agent_assembly; print(agent_assembly.__version__)"`
  plus `agent_assembly/bin/aasm --version` (path inside the installed
  package) to confirm both halves of the wheel are correct.
- Confirm `pip install agent-assembly --dry-run` resolves to `<pypi_version>`
  and not a yanked-higher-version shadow (see the yanked-but-higher quirk).
