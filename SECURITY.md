# Security Policy

## Reporting a vulnerability

<!-- BEGIN GENERATED: security_contact -->
Report security vulnerabilities privately to **security@agent-assembly.com**. Do not open a public issue or discussion for a security report.

| Response stage | Target |
| --- | --- |
| Acknowledgement | Within 2 business days |
| Initial assessment | Within 5 business days |

> **Legacy address.** `security@agent-assembly.dev` remains a legacy compatibility alias. During the in-progress migration to the canonical `security@agent-assembly.com` identity, the legacy address continues to receive mail via Cloudflare Email Routing, so a report sent there still reaches us. The canonical mailbox is not yet live-sending.
<!-- END GENERATED: security_contact -->

Please do not open public issues for security reports.

## Canonical package name

The **only** official distribution of this SDK on PyPI is:

| Ecosystem | Canonical name |
|---|---|
| PyPI | [`agent-assembly`](https://pypi.org/project/agent-assembly/) |

Anything else — a hyphen/underscore variant, a near-miss spelling, or a
look-alike namespace — is **not us**. The published package is a trust path
straight into your application's process: by the time runtime policy evaluates,
the package's code is already executing. Treat a typosquat as hostile and
install only the name above.

## Verifying what you installed

Every release is published exclusively through the operator-gated, OIDC-backed
release pipeline (`.github/workflows/release-python.yml`), which ships two
consumer-verifiable signals:

### 1. PEP 740 attestations (provenance)

Wheels and sdists are uploaded via PyPI Trusted Publishing with PEP 740 digital
attestations enabled. The attestation is minted from the release workflow's
OIDC identity — an artifact uploaded outside that pipeline cannot carry one.

- Open the project's **PyPI files page**:
  <https://pypi.org/project/agent-assembly/#files> — each file lists its
  **Attestations** (Sigstore provenance) when produced by the sanctioned
  pipeline.
- An artifact with **no attestation** was not produced by our release workflow.
  Do not trust it.

### 2. CycloneDX SBOM

Each tagged release attaches a CycloneDX Software Bill of Materials,
`sbom.cdx.json`, to its **GitHub Release**:
<https://github.com/ai-agent-assembly/python-sdk/releases>

The SBOM enumerates the resolved dependency set so you can cross-check it
against advisory feeds and detect a poisoned transitive dependency. Download it
from the matching release tag and audit it with any CycloneDX-aware scanner.

## Supply-chain controls in CI

- **Advisory gate:** `ci.yaml` runs `pip-audit` against the locked environment
  on every push and pull request; a known-vuln dependency fails CI.
- **Locked dependencies:** the resolved versions in `uv.lock` are what the
  SBOM and the published wheels are built from.
