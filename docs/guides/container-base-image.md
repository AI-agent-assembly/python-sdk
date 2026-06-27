# Governed container base image

Run a containerized Python agent that is **governed by default** — no extra install step.
The Agent Assembly project publishes a governed Python base image to GitHub Container
Registry that already bundles the `aasm` CLI and the `agent-assembly` Python SDK, so a
`FROM` line is all it takes to make your agent ready for governance.

## What it is

```text
ghcr.io/ai-agent-assembly/python:{3.12,3.13,3.14}-slim
```

A governed base image built on top of the official `python:<runtime>-slim` images. Each
image ships with:

- the **`aasm` CLI** on the `PATH` (`aasm --version` works out of the box), and
- the **`agent-assembly` Python SDK** pre-installed and importable —
  `from agent_assembly import init_assembly` works with **no extra `pip install`**.

Because the SDK is already present, a Python agent built `FROM` this image can call
`init_assembly()` and be wired into the governance runtime the moment it starts.

!!! note "Three runtimes, one contract"
    Images are published for Python **3.12**, **3.13**, and **3.14** — the same matrix the
    SDK is tested against. Pick the runtime that matches your agent; the bundled SDK and CLI
    behave identically across all three.

## Tags — how to choose

There are two families of tags: **immutable** (pinned, reproducible) and **moving**
(convenient, but they change under you).

| Tag | Example | Mutable? | Use it for |
| --- | --- | --- | --- |
| `python:<runtime>-<core-version>` | `python:3.14-slim-v0.0.1-rc.2` | **No** — immutable | **CI and production.** Reproducible, byte-for-byte stable. |
| `python:<runtime>` | `python:3.14-slim` | Yes — moves per release | Local experiments on a fixed Python runtime. |
| `python:latest` | `python:latest` | Yes — moves per release | Quick one-off tries only. |

`<core-version>` is the **Agent Assembly core / `aa-runtime` release** baked into the
image — it is also the version of the `aasm` CLI inside the image. Pinning
`python:3.14-slim-v0.0.1-rc.2` therefore pins *both* the Python runtime and the exact
governance core/CLI version, which is what makes the build reproducible.

!!! warning "Pin the immutable tag in CI and production"
    Never deploy `:latest` or a bare `python:<runtime>` tag to production — they move every
    release and will silently change the core/CLI version under your agent. Always pin the
    immutable `python:<runtime>-<core-version>` form.

## Quick start

A minimal agent image that inherits governance from the base image:

```dockerfile
# Pin the immutable tag — Python 3.14 runtime + a fixed governance core/CLI version.
FROM ghcr.io/ai-agent-assembly/python:3.14-slim-v0.0.1-rc.2

WORKDIR /app

# Your agent's own dependencies. The agent-assembly SDK is already installed.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent.py .

CMD ["python", "agent.py"]
```

Both the CLI and the SDK are ready with no extra install:

```bash
# Inside the image, the governance CLI is on the PATH:
aasm --version

# ...and the SDK imports with nothing else to install:
python -c "from agent_assembly import init_assembly; print('SDK ready')"
```

Your `agent.py` then opts into governance the usual way:

```python
from agent_assembly import init_assembly

with init_assembly(
    gateway_url="http://aa-runtime:7391",
    api_key="dev-key",
    agent_id="my-agent",
):
    run_my_agent()
```

See the [Quick Start](../quick-start.md) for the full `init_assembly()` walkthrough.

## Choosing the SDK — the `SDK_VERSION` build-arg

The base image's `Dockerfile` exposes an **optional** `SDK_VERSION` build-arg that controls
which `agent-assembly` SDK release gets baked in.

| `SDK_VERSION` | Result |
| --- | --- |
| *unset* (default) | Installs the **latest stable** SDK release; if no stable release exists yet, the **latest pre-release**. |
| set to a version | Installs **exactly** that version — e.g. `SDK_VERSION=0.0.1b5`. |

```bash
# Default — let the image resolve the newest appropriate SDK release:
docker build -t my-agent .

# Pin an exact SDK version for a fully reproducible build:
docker build --build-arg SDK_VERSION=0.0.1b5 -t my-agent .
```

!!! tip "Published images already pin the SDK"
    The images published to GHCR are built with `SDK_VERSION` pinned to a specific SDK
    release, so an immutable tag gives you a known SDK version. A bare `docker build` of the
    base `Dockerfile` (no `--build-arg`) gets the resolved default instead.

## Best practices

- **Pin the immutable tag in CI and production.** Use
  `python:<runtime>-<core-version>` (e.g. `python:3.14-slim-v0.0.1-rc.2`); never `:latest`.
- **Pair the image with the `aa-runtime` sidecar.** The image makes your agent
  *governance-ready*, but the in-process SDK layer is **not a security boundary on its
  own** — point `init_assembly()` at an `aa-runtime` instance (sidecar or service) so policy
  is actually enforced. See [Runtime compatibility](../compatibility/runtime.md).
- **Keep the image core-version aligned with your runtime.** The `<core-version>` in the
  image tag should match the `aa-runtime` version you enforce against; mixing versions can
  surface protocol skew.
- **Rebuild per release.** When a new core or SDK release ships, bump the pinned tag (and
  `SDK_VERSION` if you set it) and rebuild — don't rely on a moving tag to pull updates for
  you.

## See also

- **Canonical core guide** — the cross-language reference for the governed base images:
  [`agent-assembly/docs/src/usage-guide/container-base-images.md`](https://github.com/ai-agent-assembly/agent-assembly/blob/master/docs/src/usage-guide/container-base-images.md)
- **ADR 0009** — the design rationale for versioned base-image tags and SDK pinning:
  [`agent-assembly/docs/src/adr/0009-versioned-base-image-tags-and-sdk-pinning.md`](https://github.com/ai-agent-assembly/agent-assembly/blob/master/docs/src/adr/0009-versioned-base-image-tags-and-sdk-pinning.md)
- [Runtime compatibility](../compatibility/runtime.md) — which `aa-runtime` versions a given
  SDK release speaks to.
