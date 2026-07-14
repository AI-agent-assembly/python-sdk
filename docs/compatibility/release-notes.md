# Release notes

Release notes for the Agent Assembly Python SDK. Versions follow [SemVer](https://semver.org/) starting from `1.0.0`; pre-1.0 releases (the current `0.x.y` line) may include breaking changes between minor versions and are tracked in the [GitHub releases](https://github.com/ai-agent-assembly/python-sdk/releases) feed.

!!! info "0.x development"
    The SDK is in active 0.x development; per-release notes are minimal. Track full changes via [the commits to `master`](https://github.com/ai-agent-assembly/python-sdk/commits/master) and the [GitHub releases](https://github.com/ai-agent-assembly/python-sdk/releases) feed.

## 0.0.1-rc.5

Fifth **release candidate** on the `0.0.1` line. This release tracks the published
`agent-assembly` core **`v0.0.1-rc.5`**: the bundled `aasm` runtime binary and the
compiled `aa-ffi-python` extension are pinned to that core tag.

Headline is the **agent-registration fix**: the SDK now registers against the
gateway's derived gRPC endpoint (`:50051`) instead of the REST base URL, and fails
loud — warning and exposing an unregistered state — when that register call cannot
reach the gateway, so a silent registration gap can no longer look healthy.

- Register against the derived gRPC endpoint (`:50051`) rather than the REST base,
  and warn loudly / expose the unregistered state when the register call fails
  (AAASM-4547).
- Relax the `pydantic` / `protobuf` / `grpcio` dependency floors and add a CI
  dependency-resolution guard so an over-tight floor can no longer wedge resolution
  (AAASM-4518).
- Docs: per-framework quick-start tabs across the SDK docs (AAASM-4558 / AAASM-4559 /
  AAASM-4560).
- Bump the `aa-core` / `aa-proto` / `aa-sdk-client` pins in `aa-ffi-python` to the
  core `v0.0.1-rc.5` tag.

## 0.0.1-rc.4

Fourth **release candidate** on the `0.0.1` line. This release tracks the published
`agent-assembly` core **`v0.0.1-rc.4`**: the bundled `aasm` runtime binary and the
compiled `aa-ffi-python` extension are pinned to that core tag.

Headline is the **release wheel matrix**: the SDK now builds and publishes
`cp313`/`cp314` wheels alongside `cp312`, and a CI drift guard keeps the release
matrix and the supported-interpreter list in lockstep so a missing ABI can no
longer ship silently.

- Build `cp313`/`cp314` wheels in the release matrix (AAASM-4446).
- Add a wheel-python-matrix drift guard (script + fixture suite) that runs on every
  PR, failing if the release interpreter matrix diverges from the declared support
  window (AAASM-4453).
- Repoint quick-start and framework-support LangChain imports to `langchain-classic`
  (AAASM-4451).
- LangGraph subgraph-as-node lineage tracking and sync-subgraph idempotency fixes
  (AAASM-4472 / AAASM-4474).
- Bump Python dependencies to latest stable and migrate the LangGraph graph API
  (AAASM-4434).
- Warn when `~/.aasm/config.yaml` is group/other-readable.
- Docs: per-framework quick-start tabs, and clarify local-mode transports
  (:7391 REST + :50051 gRPC) (AAASM-4465).
- Bump the `aa-core` / `aa-proto` / `aa-sdk-client` pins in `aa-ffi-python` to the
  core `v0.0.1-rc.4` tag.

## 0.0.1-rc.3

Third **release candidate** on the `0.0.1` line. This release tracks the published
`agent-assembly` core **`v0.0.1-rc.3`**: the bundled `aasm` runtime binary and the
compiled `aa-ffi-python` extension are pinned to that core tag (AAASM-4056).

Changes since rc.2 are limited to the core-pin promotion — there is no new SDK
surface:

- Bump the `aa-core` / `aa-proto` / `aa-sdk-client` pins in `aa-ffi-python` to the
  core `v0.0.1-rc.3` tag. rc.3 is a security-hardening cut of the core (three
  verified sweeps) and fixes the `aa-gateway` crates.io publish break (AAASM-4056).

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
