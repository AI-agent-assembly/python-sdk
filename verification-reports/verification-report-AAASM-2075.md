# Verification report — AAASM-2075

**Story:** python-sdk README and docs are production-ready and linked from org documentation
**Parent Epic:** AAASM-2072 (Production documentation coverage across org repos)
**Branch:** `v0.0.1/AAASM-2075/docs/readme_and_docs`

## Acceptance criteria

| Area | Acceptance criteria | Status | Evidence |
| --- | --- | --- | --- |
| README | Purpose, installation, quick start, version/release state, runtime dependency, support links | ✅ | Live-PyPI install with `[runtime]` extra; new **Project status**, **Ecosystem**, and **Support** sections; existing purpose/quick-start/requirements retained |
| Docs | init flow, framework examples, configuration, troubleshooting, type checking, release process, compatibility with core runtime | ✅ | init-flow = existing Architecture page; added `usage/{configuration,framework-examples,type-checking}.md` and `development/{troubleshooting,compatibility,release-process}.md` |
| Cross-links | README links to core repo, docs site, spec, release notes, org profile | ✅ | **Ecosystem** section links org profile, core runtime (spec lives there), canonical docs site, sibling SDKs, Homebrew tap; release notes linked from **Project status** |
| Examples | Python examples current and validated or marked as planned | ✅ | Replaced leaked type-checking template (`type_checking_example.py` + README) with a real mypy-clean example; added `examples/README.md` status index marking `basic_usage.py` illustrative and framework examples planned |
| Validation | Links and install commands checked | ✅ | See below |

## Validation performed

- **`mkdocs build --strict`** (via `uv --group docs`): all 6 new pages render; the only
  strict-mode warning is the `git-committers` plugin requesting a GitHub API token
  (environmental, not a content defect). A non-strict build produced **zero** link/nav
  warnings.
- **README relative links**: all 14 `./…` links resolve to existing files (scripted check).
- **Type-checking example**: `mypy examples/type_checking/type_checking_example.py` → clean;
  `ruff check` + `ruff format --check` → pass; the script runs and prints the expected output.
- **Install commands**: `agent-assembly` is published on PyPI; the published metadata declares
  `provides_extra: ['all', 'runtime']`, so `pip install 'agent-assembly[runtime]'` is valid.

## Notes

- The mode names in the Configuration/Troubleshooting docs (`auto`/`ebpf`/`proxy`/`sdk-only`)
  and `enforcement_mode` (`enforce`/`observe`/`disabled`) were taken from
  `agent_assembly/core/assembly.py`, not from prose, to avoid drift.
- The leaked `type_checking_example.py` referenced a "Slack MCP Server package" — the same
  template-leakage class of issue tracked separately under AAASM-2053; here it is fixed only
  for the example file.
- Compatibility page deliberately points to the native crate's git-SHA pin as the
  wire-compat source of truth rather than inventing a version matrix; no conformance-vector
  directory exists in this repo.
