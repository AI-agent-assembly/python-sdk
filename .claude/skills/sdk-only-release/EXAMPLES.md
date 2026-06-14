# EXAMPLES.md — sdk-only-release

A concrete end-to-end run, showing the PEP 440 input form and the dry-run gate.

## Worked example — `0.0.1a9.post1`

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
