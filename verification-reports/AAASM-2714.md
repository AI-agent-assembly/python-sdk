# Verification Report — AAASM-2714

**Story:** Harmonize python-sdk FFI packaging with node-sdk / go-sdk
**Subtasks:** AAASM-2716 (impl) · AAASM-2717 (verify)
**Component:** `python-sdk`
**Branch:** `v0.0.1/AAASM-2714/harmonize_ffi_infra`

## Scope

Two infra changes only — no behavior, API, or build-config semantics changed:

1. Moved the PyO3 FFI crate `rust/aa-ffi-python/` → `native/aa-ffi-python/`,
   mirroring `node-sdk/native/aa-ffi-node` and `go-sdk/native/aa-ffi-go`.
2. Committed the crate's `Cargo.lock` (previously gitignored) for reproducible
   native builds, matching `node-sdk/native/aa-ffi-node/Cargo.lock`.

The redundant `rust/Cargo.toml` workspace wrapper (a single-member workspace)
was dropped; the crate is standalone — it inherits nothing from a workspace and
all dependency versions are explicit, exactly like `aa-ffi-node`.

### Explicitly NOT changed (per ticket)

- `pyo3 = "0.28"` version and `extension-module` feature — unchanged.
- The 3-crate git-SHA pin (`aa-core` / `aa-proto` / `aa-sdk-client` @
  `9cf8a033…`) — unchanged.
- `[lib] crate-type = ["cdylib"]` — unchanged.
- Org casing (`AI-agent-assembly`) in git-dep URLs — left as-is (separate ticket).
- Historical `verification-reports/*.md` — left as point-in-time records.

## Changes

| Area | File(s) |
|---|---|
| Crate move | `rust/aa-ffi-python/{Cargo.toml,pyproject.toml,src/lib.rs}` → `native/aa-ffi-python/…`; removed `rust/Cargo.toml` |
| Lockfile | added `native/aa-ffi-python/Cargo.lock`; `.gitignore` now ignores `native/**/target/` instead of `rust/target/` + `rust/Cargo.lock` |
| maturin | `pyproject.toml` `[tool.maturin].manifest-path` → `native/aa-ffi-python/Cargo.toml` |
| CI | `.github/workflows/native-core-build.yml` path trigger `rust/**` → `native/**` and manifest-path; `.github/dependabot.yml` cargo `directory: /rust` → `/native/aa-ffi-python` |
| Source/test | `agent_assembly/types.py` build-hint docstrings; `test/integration/test_native_core_maturin.py` manifest-path |
| Docs | `README.md`, `CONTRIBUTING.md`, `docs/architecture/index.md`, `docs/development/compatibility.md` (incl. GitHub blob link), `docs/development/troubleshooting.md` |

## Verification

| Check | Result |
|---|---|
| `git grep 'rust/aa-ffi-python'` (excluding historical verification-reports) | ✅ no matches |
| `rust/` directory removed | ✅ gone |
| `native/aa-ffi-python/Cargo.lock` tracked | ✅ `git ls-files` confirms |
| `cargo check --locked` (native/aa-ffi-python) | ✅ resolves from committed lock, compiles |
| `uv sync` | ✅ |
| `maturin develop --manifest-path native/aa-ffi-python/Cargo.toml` | ✅ built + installed `agent_assembly._core` |
| `uv run pytest test/ -q` | ✅ 423 passed, 7 skipped |
| `AAASM_RUN_MATURIN_TESTS=1 pytest test_native_core_maturin.py` | ✅ 1 passed (new path drives a real maturin build) |

Environment: macOS arm64, CPython 3.13, `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1`.
