# Release process

How a version of `agent-assembly` gets from `master` to PyPI and the documentation site.

## Versioning

The project is **pre-1.0** and releases from the `0.0.x` line. Until `1.0.0`, minor versions
may carry breaking changes; consumers who need a frozen contract should pin an exact version.
The canonical version lives in `pyproject.toml` (`[project].version`).

## Distribution: platform wheels

The SDK is published as a set of wheels built with [`maturin`](https://www.maturin.rs/) so
the optional native runtime binary is bundled per platform — `pip install` selects the right
wheel by platform tag, no post-install scripts needed:

| Artifact | Contents |
| --- | --- |
| `agent_assembly-<v>-…-manylinux_*_x86_64.whl` / `…aarch64.whl` | SDK + Linux `aasm` binary |
| `agent_assembly-<v>-…-macosx_*_arm64.whl` / `…x86_64.whl` | SDK + macOS `aasm` binary |
| `agent_assembly-<v>.tar.gz` (sdist) | Pure-Python source |

`pip install agent-assembly` gets the pure-Python client; `pip install 'agent-assembly[runtime]'`
pulls the platform wheel that bundles the binary. See [Installation](https://github.com/AI-agent-assembly/python-sdk#installation).

## Publishing: Trusted Publisher (OIDC)

Releases publish through a **PyPI Trusted Publisher** — GitHub Actions exchanges a short-lived
OIDC token with PyPI at publish time, so there is **no long-lived API token stored in CI**.
The publish job runs in the `pypi` GitHub Environment.

The release workflow (`.github/workflows/release-python.yml`) builds the full wheel matrix and
publishes when a release tag is pushed. A `workflow_dispatch` run can build artifacts as a
dry-run without publishing.

## Cutting a release

1. Bump `[project].version` in `pyproject.toml` (and keep `agent_assembly.__version__` in sync).
2. Land it on `master` through the normal PR flow.
3. Push the release tag — the workflow builds every platform wheel + sdist and publishes them
   to PyPI via the Trusted Publisher.
4. Verify the wheels appear on the [PyPI release page](https://pypi.org/project/agent-assembly/#history)
   and carry platform tags (`manylinux_*`, `macosx_*`), not `none-any`.

## Documentation versioning

Docs are versioned with [`mike`](https://github.com/jimporter/mike): every push to `master`
deploys to **`latest`**, and a release promotes to **`stable`**. Readers switch versions with
the selector at the top of the [documentation site](https://ai-agent-assembly.github.io/python-sdk/).

## Release notes

Release notes are tracked on the [Release notes](../release-notes/index.md) page and the
[GitHub releases](https://github.com/AI-agent-assembly/python-sdk/releases) feed.
