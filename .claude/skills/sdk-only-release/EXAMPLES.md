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

---

## Two cases — when to use this skill

The `sdk-only-release` skill's [SKILL.md SOP](SKILL.md#release-coordination-sop--when-agent-assembly-is-also-releasing) defines two release shapes. The worked example above (`0.0.1a9.post1`) is a **Case B** scenario — SDK-only release with the bundled `aasm` binary already published from the previous coordinated cycle. The walkthrough below shows the **Case A** coordinated cycle.

## Case A — coordinated cycle (wait for agent-assembly)

Worked example for the SOP. **Scenario**: operator wants to publish `agent-assembly==0.0.1b3` **alongside** agent-assembly `v0.0.1-beta.3` — both carry the same content cycle. The SOP requires the SDK dispatch to wait for the upstream tag + the auto-bump PR.

**1. Verify the agent-assembly tag exists and `release.yml` finished green.**

```bash
$ gh release view v0.0.1-beta.3 --repo ai-agent-assembly/agent-assembly \
    --json tagName,publishedAt
{"tagName":"v0.0.1-beta.3","publishedAt":"2026-..."}

$ gh run list --repo ai-agent-assembly/agent-assembly --workflow release.yml \
    --branch v0.0.1-beta.3 --limit 1 --json conclusion,name
[{"name":"Release","conclusion":"success"}]
```

If the release is missing or the run is still in progress, STOP — do not dispatch the SDK release yet.

**2. Verify the `bot/aa-ffi-pin-v0.0.1-beta.3` PR opened on this repo.**

```bash
$ gh pr list --repo ai-agent-assembly/python-sdk --head bot/aa-ffi-pin-v0.0.1-beta.3 \
    --json number,title,mergedAt
[{"number":NNN,"title":"🤖 (aa-ffi-python): Bump aa-core/aa-proto/aa-sdk-client pin to v0.0.1-beta.3","mergedAt":null}]
```

If no PR is listed, the upstream `update-python-sdk-ffi-pin` job (AAASM-2883) hasn't run yet. Wait, then re-probe.

**3. Review + merge the auto-bump PR.** The PR moves all three shared `git-SHA` pins (`aa-core`, `aa-proto`, `aa-sdk-client`) in `native/aa-ffi-python/Cargo.toml` to the new agent-assembly tag commit (and regenerates `Cargo.lock`). The single-SHA invariant from ADR 0002 / AAASM-2559 is preserved.

**4. ONLY NOW dispatch `release-python.yml`.** Same mechanics as the `0.0.1a9.post1` example above — `dry-run=true` first, then `dry-run=false`. Use `binary_source_tag=v0.0.1-beta.3` (NOT the previous tag) so the wheels bundle the new `aasm-*.tar.gz` assets, and `pypi_version=0.0.1b3` (the PEP 440 form of the agent-assembly tag).

```bash
gh workflow run release-python.yml \
  --repo ai-agent-assembly/python-sdk \
  --ref master \
  -f pypi_version=0.0.1b3 \
  -f binary_source_tag=v0.0.1-beta.3 \
  -f dry-run=true
```

**5. Verify on the registry** (same probes as the `0.0.1a9.post1` example: `pip index versions agent-assembly` confirms `0.0.1b3` is the latest; downloading a wheel and inspecting the bundled `aasm` binary should match the new agent-assembly Release artifacts).

### Anti-example — what happens if you skip steps 1-3

This is the 2026-06-15 foot-gun the SOP prevents:

- **02:22 UTC** — operator dispatched `release-python.yml` with `pypi_version=0.0.1b2` while agent-assembly's latest release was still `v0.0.1-beta.1`. `binary_source_tag` resolved to that previous tag. `dry-run` defaulted to false. **PyPI accepted the publish**, bundling wheels with the previous agent-assembly content.
- **09:36 UTC** — agent-assembly's actual `v0.0.1-beta.2` tag cut (commit `0aa9c945`, AAASM-3004) → `notify-downstream` fired the coordinated republish. `release-python.yml` tried to re-publish `0.0.1b2` with the new content carrying the AAASM-3000 IPC fix. **PyPI 400'd** with `File already exists ('agent_assembly-0.0.1b2-cp312-cp312-macosx_10_12_x86_64.whl'). See https://pypi.org/help/#file-name-reuse`.
- **Net**: `agent-assembly==0.0.1b2` on PyPI carries the OLD content (no AAASM-3000 fix). The file-name slot is permanently burnt — PyPI explicitly disallows file-name reuse even after yank (see the linked help page). The fix had to ship under a different SDK version cut later.

The verification probes in steps 1-3 above make this impossible to repeat: any of them failing forces the operator to stop and resolve before dispatch.
