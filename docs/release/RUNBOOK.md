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

## 2. Verification

After the workflow completes, verify on PyPI:

```bash
pip index versions agent-assembly
python -c "import importlib.metadata as m; print(m.version('agent-assembly'))"
pip download --no-deps agent-assembly==<pypi_version> -d /tmp/aa-verify
```

The downloaded wheel should contain `agent_assembly/bin/aasm` at the
top-level package path.

## 3. Recovery — when a publish fails

PyPI publishes are effectively immutable. A failed publish that uploaded
partial state (e.g. some wheels but not the sdist) is recovered by
bumping `pypi_version` to the next available PEP 440 slot and re-running
the workflow with the same `binary_source_tag`. Do not delete a release
from PyPI to retry — the grace window is short and other operators may
already be depending on the partial state.
