# python-sdk release runbook

> Step-by-step procedure for cutting an `agent-assembly` (Python) release.
> Companion to `agent-assembly/docs/release/RUNBOOK.md` for the
> coordinated product-line release path. Tracked under AAASM-2851
> (decoupled release story) and AAASM-2858 (this runbook).

This runbook assumes the operator has push rights to
`AI-agent-assembly/python-sdk` and that the `agent-assembly` PyPI
project has the python-sdk repo + `release-python.yml` workflow path
configured as its PyPI Trusted Publisher.

The python-sdk releases one wheel + sdist set per workflow run:

| Artifact | Contents |
| --- | --- |
| `agent-assembly-<version>.tar.gz` | Source distribution (pure-Python sources) |
| `agent_assembly-<version>-cp312-*-{manylinux_x86_64,manylinux_aarch64,macosx_x86_64,macosx_arm64}.whl` | Per-platform wheel bundling the `aasm` sidecar binary at `agent_assembly/bin/aasm` |

The `aasm` binary inside each wheel is downloaded from an agent-assembly
GitHub Release at build time. `runtime.py` resolves it via the
`WHEEL_BUNDLED_BIN` search path at install time.

---

## 1. Coordinated release (the default path)

The coordinated release publishes `agent-assembly` at the same version
as an agent-assembly tag. This is the path that fires automatically when
`agent-assembly`'s `release.yml` sends a `repository_dispatch` event
after a tag push — see `agent-assembly/docs/release/RUNBOOK.md` section
3 for the dispatcher contract. To dispatch manually:

```bash
gh workflow run release-python.yml \
  --repo ai-agent-assembly/python-sdk \
  --ref master \
  -f pypi_version=0.0.1a9 \
  -f binary_source_tag=v0.0.1-alpha.9 \
  -f dry-run=false
```

What happens:

1. The workflow checks out master.
2. `pypi_version` (PEP 440, e.g. `0.0.1a9`) is stamped on
   `pyproject.toml`'s `project.version`.
3. For each of the 4 wheel jobs, the matching `aasm-*.tar.gz` from the
   `binary_source_tag` agent-assembly GitHub Release is downloaded and
   staged at `agent_assembly/bin/aasm` before `maturin build` runs.
4. The sdist + 4 wheels are uploaded as workflow artifacts.
5. The `publish-to-pypi` job downloads all artifacts and uploads them to
   PyPI via Trusted Publisher OIDC.

Use coordinated releases whenever the change touches the `aasm` binary,
any shared Rust crate, or a wire-protocol-level surface that spans the
SDK and the sidecar. This is the normal product-line cadence.

## 2. SDK-only hotfix mode

If only the Python surface of `agent-assembly` needs a fix (the `aasm`
sidecar binary bundled inside each wheel is healthy), you can publish a
new PyPI version **without** cutting a new agent-assembly tag.

### When to use

- A bug exists only in the Python code under `agent_assembly/`.
- The `aasm` binary that the previous release bundled is correct.
- You want to ship the fix fast without re-publishing 14 Rust crates,
  rebuilding Docker images, opening a Homebrew tap PR, etc.

### How to dispatch

```bash
gh workflow run release-python.yml \
  --repo ai-agent-assembly/python-sdk \
  --ref master \
  -f pypi_version=0.0.1a8.post1 \
  -f binary_source_tag=v0.0.1-alpha.8 \
  -f dry-run=false
```

What happens:

1. The workflow runs against master.
2. `pypi_version` (e.g. `0.0.1a8.post1`) is stamped on
   `pyproject.toml`'s `project.version`.
3. `binary_source_tag` (e.g. `v0.0.1-alpha.8`) is the agent-assembly
   GitHub Release whose `aasm-*.tar.gz` binaries are downloaded and
   staged at `agent_assembly/bin/aasm` for each per-platform wheel.
   This is the same mechanism used by the coordinated path — the wheel
   bundles the unchanged `v0.0.1-alpha.8` `aasm` binary.
4. The sdist + 4 wheels build and upload to PyPI as
   `agent-assembly==0.0.1a8.post1`.
5. Users running `pip install agent-assembly==0.0.1a8.post1` get the new
   Python code bundled with the same `aasm` binary they had before.

### When NOT to use (use the coordinated agent-assembly release instead)

- A bug exists in the `aasm` binary or any shared Rust crate.
- New features that span SDK + binary (e.g. a new gRPC method).
- Routine version bumps that should ship across the whole product line.

### Version naming convention

Use PEP 440 `.postN` post-release segments on the parent SDK version:
`0.0.1a8.post1`, `0.0.1a8.post2`, etc. Reserve `0.0.1a9` (and other
clean `aN` slots) for coordinated agent-assembly releases.

> **Important PEP 440 note vs node-sdk.** The node-sdk uses a
> `0.0.1-alpha.8.1` semver pre-release suffix; that string is **not** a
> valid PEP 440 version and pip will reject it. The `.postN` form is the
> only correct PEP 440 spelling for "a small fix on top of the parent
> pre-release". Do not invent forms like `0.0.1a8.1` or
> `0.0.1-alpha.8.1` for python-sdk — both are invalid.

### No "main-only" choice — single-artifact-set asymmetry vs node-sdk

The node-sdk's `publish_mode=main-only` exists because that workflow
emits five artifacts (`@agent-assembly/sdk` + four
`@agent-assembly/runtime-*` per-platform packages), and SDK-only hotfix
mode means "publish the main SDK package, skip the runtime ones".

The python-sdk has no such choice because it emits a **single artifact
set** (one sdist plus four per-platform wheels). The Python code and the
bundled `aasm` binary ship together inside the same wheel; there is no
separate "runtime" package on PyPI to skip. Consequently:

- There is no `publish_mode` input on `release-python.yml`.
- `dry-run=false` together with `pypi_version` set always means a real
  publish — there is no half-step that produces only the Python source
  and reuses old wheels.
- The "SDK-only" nature of the hotfix is expressed entirely by the
  `pypi_version` (`.postN` suffix) and by reusing the previous
  release's `binary_source_tag` so the bundled `aasm` binary is
  unchanged byte-for-byte.

### Documentation snapshots — `workflow_dispatch` paths skip release-channel docs

`workflow_dispatch` publishes (including SDK-only hotfixes and dry-runs)
do **not** cut a new release-channel docs snapshot. There is no upstream
agent-assembly tag to label the snapshot with, and the downstream docs
workflow has nothing meaningful to deploy. Two gates implement this:

- **AAASM-2857**: the `publish-release-tag` job in `release-python.yml`
  is gated on `event_name == 'repository_dispatch'`. Only the
  coordinated-release path uploads the `release-tag` artifact that the
  docs workflow consumes.
- **AAASM-2868**: the `Deploy release documentation (channel)` job in
  `documentation.yaml` is symmetrically gated on
  `github.event.workflow_run.event == 'repository_dispatch'`. Without
  this gate, every `workflow_dispatch` source run would trigger a
  failed download of the (non-existent) `release-tag` artifact.

**Net effect on SDK-only hotfix mode**: the new `pypi_version` is
published cleanly to PyPI, but no new release-channel docs snapshot
is cut. The `latest`-channel docs still rebuild and deploy on the next
master push — that path is unaffected by these gates. If you need
release-channel docs for an SDK-only hotfix, you must dispatch the
coordinated agent-assembly release flow instead (which is exactly the
"when NOT to use SDK-only mode" guidance above).

### Pre-flight checks

The workflow's `binary_source_tag` resolution step calls the
agent-assembly GitHub Release API and fails fast if the referenced tag
does not have all four `aasm-*.tar.gz` assets attached. This guards
against the common mistake of pointing `binary_source_tag` at a
not-yet-published agent-assembly tag.

The PyPI upload step verifies that `pypi_version` does **not** already
exist on the `agent-assembly` PyPI project — PyPI publishes are
effectively immutable within minutes of upload, so re-publishing the
same version is treated as a fatal user error rather than a no-op.

## 3. Verification

After the workflow completes, verify on PyPI:

```bash
pip index versions agent-assembly
python -c "import importlib.metadata as m; print(m.version('agent-assembly'))"
pip download --no-deps agent-assembly==<pypi_version> -d /tmp/aa-verify
```

The downloaded wheel should contain `agent_assembly/bin/aasm` at the
top-level package path. For SDK-only hotfix runs, the `aasm` binary
inside the wheel should be byte-identical to the one shipped in the
parent release at `binary_source_tag`.

## 4. Recovery — when a publish fails

PyPI publishes are effectively immutable. A failed publish that uploaded
partial state (e.g. some wheels but not the sdist) is recovered by
bumping `pypi_version` to the next available PEP 440 slot and re-running
the workflow with the same `binary_source_tag`. Do not delete a release
from PyPI to retry — the grace window is short and other operators may
already be depending on the partial state.

If the failure is in the `binary_source_tag` resolution step (e.g. the
referenced agent-assembly tag does not yet have all four `aasm-*.tar.gz`
assets), fix the underlying coordination problem first — usually that
means running the coordinated release for `binary_source_tag` before
attempting the SDK-only hotfix.
