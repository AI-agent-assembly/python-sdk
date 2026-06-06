# Verification Report — AAASM-2665

**Story:** AAASM-2665 — ⚡ (python-sdk): Per-PR matrix trim + concurrency + debug native build
**Epic:** AAASM-2659 — ⚡ (org): Org-wide CI/CD performance & billing hardening
**Component:** `python-sdk` (PUBLIC) — CI workflows under `.github/workflows/`
**Date:** 2026-06-06

---

## Summary

Hardens the per-PR CI footprint for the `python-sdk` reusable-workflow chain
(`ci.yaml` → `rw_run_all_test_and_record.yaml` → `rw_build_and_test.yaml`) while
retaining the full 4-OS matrix on `push` to `master`, scheduled, and release runs.

Changes (one commit each):

- **Concurrency** `cancel-in-progress` added to `ci.yaml`, `native-core-build.yml`,
  `benchmarks.yml`, `type-check.yml` (previously only `documentation`/`release` had it).
- **Matrix** `operating-systems` is now a `workflow_call` input on `rw_build_and_test.yaml`
  (default = the existing full 4-OS list). It is threaded through
  `rw_run_all_test_and_record.yaml` (default-preserving) and computed in `ci.yaml`:
  `["ubuntu-latest"]` for `pull_request`, the full 4-OS list otherwise.
- **Native build** `native-core-build.yml` now runs a **debug** `maturin develop`
  (dropped `--release`) and its `pull_request` `paths` are narrowed from
  `agent_assembly/**` to `rust/**` + the two FFI-binding Python files
  (`agent_assembly/__init__.py`, `agent_assembly/types.py`, the only modules importing `_core`).
- **Benchmarks** gated behind a `benchmark` PR label (`pull_request: types: [labeled]`
  + `if: contains(github.event.pull_request.labels.*.name, 'benchmark')`), keeping the
  noisy suite off the default per-PR path.
- **CI Success** aggregate gate added to `ci.yaml` (`needs: [build-and-test_all]`,
  `if: always()`), collapsing the reusable-workflow fan-out into a single stable
  required check.

## Acceptance criteria

| # | Criterion | Result |
| --- | --- | --- |
| 1 | `cancel-in-progress` concurrency on `ci.yaml`, `native-core-build.yml`, `benchmarks.yml`, `type-check.yml` | ✅ `group: ${{ github.workflow }}-${{ github.ref }}` + `cancel-in-progress: true` present in all four (grep-verified). |
| 2 | `operating-systems` parameterised in `rw_build_and_test.yaml`; default identical to current 4-OS | ✅ New `workflow_call` input, `default: '["ubuntu-latest", "ubuntu-22.04", "macos-latest", "macos-14"]'`; the three matrix jobs reference `${{ inputs.operating-systems }}`. No-override callers (e.g. `ci_includes_e2e_test.yaml`) are byte-for-byte equivalent. |
| 3 | PRs run ubuntu-only; master/scheduled/release run full 4-OS | ✅ `ci.yaml` passes `["ubuntu-latest"]` when `github.event_name == 'pull_request'`, else the full list, forwarded through `rw_run_all_test_and_record.yaml`. |
| 4 | `native-core-build.yml` uses debug `maturin develop` | ✅ `--release` removed from the maturin step. |
| 5 | `native-core-build.yml` trigger narrowed from `agent_assembly/**` to `rust/**` + FFI bindings | ✅ `paths` now `rust/**`, `agent_assembly/__init__.py`, `agent_assembly/types.py`, the workflow file itself. |
| 6 | Benchmarks gated behind a label/schedule | ✅ `types: [labeled]` + job-level `if` on the `benchmark` label. |
| 7 | `CI Success` aggregate gate added | ✅ `ci-success` job in `ci.yaml`, fails on upstream `failure`/`cancelled`, passes on success/skip. |
| 8 | All touched workflow YAML parses | ✅ `python3 -c "import yaml; yaml.safe_load(...)"` clean on all six files. |

## Validation performed

```
# YAML parse (all six touched workflows): OK
# concurrency cancel-in-progress present in all four target files: OK
# rw_build_and_test default OS list == prior hardcoded 4-OS list (behaviour preserved): OK
```

## Flagged for maintainer decision (not changed in this PR)

- **External reusable-workflow pin.** `rw_run_all_test_and_record.yaml` and
  `rw_build_and_test.yaml` reference
  `Chisanan232/GitHub-Action_Reusable_Workflows-Python/...@master`. Pinning to a
  SHA/tag is a supply-chain hardening item but requires the maintainer to choose the
  pin (a `master` move could otherwise silently break CI). Left as-is pending that choice.
- **Commented-out e2e `schedule` cron.** `ci_includes_e2e_test.yaml` has a disabled
  weekly cron (`'33 19 * * 2'`). Re-enabling vs deleting is a product/ops decision
  (it consumes the e2e Slack-token secret on a schedule). Left commented pending a decision.

## Front-end design-spec fidelity

N/A — this is a CI/CD-only change with no UI surface.
