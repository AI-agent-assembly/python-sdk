# Release notes

Release notes for the Agent Assembly Python SDK. Versions follow [SemVer](https://semver.org/) starting from `1.0.0`; pre-1.0 releases (the current `0.x.y` line) may include breaking changes between minor versions and are tracked in the [GitHub releases](https://github.com/ai-agent-assembly/python-sdk/releases) feed.

!!! info "0.x development"
    The SDK is in active 0.x development; per-release notes are minimal. Track full changes via [the commits to `master`](https://github.com/ai-agent-assembly/python-sdk/commits/master) and the [GitHub releases](https://github.com/ai-agent-assembly/python-sdk/releases) feed.

## 0.0.1-rc.2

Second **release candidate** on the `0.0.1` line. This release tracks the published
`agent-assembly` core **`v0.0.1-rc.2`**: the bundled `aasm` runtime binary and the
compiled `aa-ffi-python` extension are pinned to that core tag (AAASM-3833).

Changes since rc.1 are limited to the core-pin promotion — there is no new SDK
surface:

- Bump the `aa-core` / `aa-proto` / `aa-sdk-client` pins in `aa-ffi-python` to the
  core `v0.0.1-rc.2` tag (AAASM-3815).

## 0.0.1-rc.1

First **release candidate** on the `0.0.1` line — promotes the Python SDK from
the `beta` channel to `rc`. This release tracks the published `agent-assembly`
core **`v0.0.1-rc.1`**: the bundled `aasm` runtime binary and the compiled
`aa-ffi-python` extension are pinned to that core tag (AAASM-3763).

Changes since beta.5 are limited to the core-pin promotion plus security and
release housekeeping — there is no new SDK surface:

- Require TLS for non-loopback gateway / op-control connections — refuse a Bearer
  API key over plaintext `http` and refuse a plaintext gRPC channel to a
  non-loopback host (AAASM-3685).
- Pin third-party reusable CI workflows to commit SHAs (AAASM-3686).
- Fix and pin the CycloneDX SBOM flag in `release-python.yml` (AAASM-3722).

## 0.0.1-beta.5

Beta iteration of the Python SDK on the `0.0.1` line. Headline of this release is
**five new framework adapters**, expanding governed-framework coverage:

- **LlamaIndex** — native adapter walkthrough (AAASM-3536)
- **Agno** — hooks `FunctionCall.execute`/`aexecute` (AAASM-3537)
- **Microsoft Agent Framework** — builtin adapter (AAASM-3538)
- **Smolagents** — wraps `Tool.__call__` (AAASM-3539)
- **Haystack** — framework adapter (AAASM-3540)

Other notable changes:

- Forward `agent_id` and the installed SDK package version through `connect`
  (AAASM-3683).
- `GatewayClient` now elides `api_key` from `__repr__` and emitter logs — token
  hygiene (AAASM-3642 / AAASM-3570).
- Supply-chain hardening: PEP 740 attestations on PyPI Trusted Publisher upload,
  per-release CycloneDX SBOM, and a `pip-audit` advisory gate in CI (AAASM-3568).
- Release safety: `release-python.yml` is now operator-dispatch-only; the core
  `repository_dispatch` auto-publish trigger was removed to stop duplicate-publish
  collisions on every core release (AAASM-3503).
- Fixed the OpenAI Agents adapter to govern the current framework API (AAASM-3528).
- Docs: python-sdk is now the authoritative framework-compatibility source; mkdocs
  search restored; GA4 + consent mode wired in.

## 0.0.1-beta.4

Beta iteration of the Python SDK on the `0.0.1` line. The bundled `aasm` runtime
binary and compiled `aa-ffi-python` extension track the `agent-assembly`
`v0.0.1-beta.3` core release.
