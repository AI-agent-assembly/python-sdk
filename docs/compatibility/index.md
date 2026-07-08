# Compatibility & Versioning

**In plain terms:** this section answers three questions — *which Python do I need?*, *which
core runtime does a given SDK build talk to?*, and *how do versions and releases work?*

| Page | What it answers |
| --- | --- |
| [Framework compatibility](frameworks.md) | Which AI-agent frameworks the SDK governs (LangChain, LangGraph, Pydantic AI, CrewAI, Google ADK, MCP, OpenAI Agents) and at what version ranges / tested versions. |
| [Runtime compatibility](runtime.md) | Supported Python versions, and how the pure-Python client vs. the pinned native extension each track the core runtime. |
| [Release process](release-process.md) | How a version goes from `master` to PyPI (platform wheels, Trusted Publisher) and the docs site. |
| [Release notes](release-notes.md) | Per-release change history. |

## Versioning policy

The SDK is **pre-1.0 (`0.x`)**. It is published and usable, but the public API is not yet
frozen: until `1.0.0`, minor versions may carry breaking changes. If you need a stable
contract, **pin an exact version** (`{{ aa.python_sdk.package_name }}=={{ aa.python_sdk.version }}`).
From `1.0.0` onward the project follows [SemVer](https://semver.org/). The canonical version
lives in `pyproject.toml` (`[project].version`) and is mirrored in
`{{ aa.python_sdk.import_name }}.__version__`.

## Core ↔ SDK compatibility matrix

The Python SDK is one of several clients (alongside the Node and Go SDKs) for the same Agent
Assembly **core runtime**. The org-wide compatibility matrix — which SDK versions are
wire-compatible with which core-runtime release — lives on the documentation hub:

- **[Documentation Hub →](https://docs.agent-assembly.com/)** — the
  cross-component compatibility matrix and the protocol specification.

For the Python-specific detail — how the pure-Python client stays forward/backward tolerant
and how the optional native extension is pinned to an exact core-runtime commit — see
[Runtime compatibility](runtime.md).
