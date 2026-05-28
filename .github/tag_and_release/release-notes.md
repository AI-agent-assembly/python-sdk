> **Pre-release dry-run.** Not for production use. Continues the
> cross-repo verification series started by v0.0.1-alpha.1 (2026-05-27)
> against the release CD pipeline. The next planned tag is v0.0.1 GA
> once all known release-infra gaps close.

### 🔧 Release-infra fixes since v0.0.1-alpha.1

This bump verifies the workflow-trigger fix from AAASM-2053:

- `.github/workflows/release.yml`, `release-validate.yml`, `type-check.yml`
  had `<your_base_branch>` / `slack_mcp` placeholders that prevented
  any of the workflows from firing on master pushes / PRs / tag pushes.
  Fixed by [PR #66](https://github.com/AI-agent-assembly/python-sdk/pull/66).
- The release-validate pipeline's docs-build cascade was failing for
  python-sdk (which uses MkDocs, not Docusaurus). Fixed upstream in
  [Chisanan232/GitHub-Action_Reusable_Workflows-Python#169](https://github.com/Chisanan232/GitHub-Action_Reusable_Workflows-Python/pull/169)
  + the `artifacts.docs: skip` knob in this repo's `intent.yaml`.

### 🔍 What this release exercises (release-infra observation)

The release-validate workflow's full cascade should now complete
cleanly. PyPI publish + sibling-repo cross-CD coordination are still
gated on the alpha-1 follow-up findings (AAASM-1253).

### Install

```bash
pip install --pre agent-assembly==0.0.1a2
```

### Refs

- Story `AAASM-2104` — pyproject bump
- Story `AAASM-1234` — F118 release-trigger
- Epic   `AAASM-1199` — Release & Distribution Pipeline
- Sibling tag this aligns with: `agent-assembly v0.0.1-alpha.2`, `node-sdk v0.0.1-alpha.2`, `go-sdk v0.0.1-alpha.2`
