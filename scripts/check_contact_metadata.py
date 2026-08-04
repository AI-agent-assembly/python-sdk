#!/usr/bin/env python3
"""Sync/audit contact identity literals against the canonical org registry.

WHY THIS EXISTS
---------------
AAASM-5520: the org's public contact identities (canonical `.com` addresses,
their legacy `.dev` aliases, and the structured security-response SLAs) are
owned by the canonical metadata registry in `ai-agent-assembly/.github`
(`metadata/org-profile.yaml`, projected to `metadata/generated/registry.json`,
per ADR 0014 / AAASM-5519). This repo previously hand-copied the maintainer
email into ``pyproject.toml`` and the security reporting address into
``SECURITY.md`` — literals that drift silently when the org migrates addresses.

This is the least-intrusive consumer strategy the ticket calls for:

* ``pyproject.toml`` — a **precise field sync/check** of the single
  ``[project].authors[].email`` value. It does NOT regenerate the manifest;
  every other byte of the TOML is preserved.
* ``SECURITY.md`` — a **bounded generated region** (BEGIN/END GENERATED:
  security_contact) carrying the canonical reporting address, the structured
  SLAs, and the labeled legacy-alias note.

CROSS-REPO DISTRIBUTION CONTRACT
--------------------------------
We **pin** the canonical registry facts to a specific `.github` commit rather
than fetching mutable `main` at build time. The pinned values live in
``CANONICAL`` below; ``REGISTRY_SOURCE`` records exactly which commit/blob they
were copied from so the pin is auditable and a re-pin is an explicit, reviewed
change. This is reproducible and network-free (CI needs no egress), and it
**fails closed**: if the pinned facts are internally inconsistent, or a consumed
file cannot be read, the check errors rather than silently passing.

Nothing here asserts the `.com` mailbox is live. The org has no Google Workspace
tenant yet (registry ``mail_platform.*_status == planned``); the legacy `.dev`
address keeps receiving via Cloudflare Email Routing during the migration. The
rendered SECURITY.md note says exactly that and never claims `.com` is sending.

Usage:
    python scripts/check_contact_metadata.py           # write/sync in place
    python scripts/check_contact_metadata.py --check    # exit non-zero on drift
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Pinned canonical facts (source of truth: ai-agent-assembly/.github).
# ---------------------------------------------------------------------------
# Copied verbatim from metadata/generated/registry.json at the commit below.
# Re-pin by updating BOTH the values and REGISTRY_SOURCE in one reviewed change.
REGISTRY_SOURCE = {
    "repo": "ai-agent-assembly/.github",
    "commit": "14db28db8fa31e7a26cc29be7c1bfcd2fb0be4aa",
    "path": "metadata/generated/registry.json",
    "blob": "af1e3842984e97ca57fd0680a1f053ad6b827f04",
}

CANONICAL = {
    # contacts.maintainers.primary — the address published as the package author.
    "maintainer_email": "team@agent-assembly.com",
    # contacts.security.primary + its single legacy alias.
    "security_email": "security@agent-assembly.com",
    "security_legacy_alias": "security@agent-assembly.dev",
    # security_policy.{acknowledgement,initial_assessment} as human text.
    "sla_acknowledgement": "2 business days",
    "sla_initial_assessment": "5 business days",
}


class ContactDriftError(RuntimeError):
    """Raised when a consumed file cannot be read or is structurally wrong."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# pyproject.toml — precise single-field sync (no manifest regeneration).
# ---------------------------------------------------------------------------
# Matches the email value inside the [project].authors inline table. We rewrite
# ONLY the quoted address, leaving the name, spacing, and every other line
# untouched, so the manifest's formatting/content is preserved byte-for-byte
# apart from the one address.
_AUTHOR_EMAIL_RE = re.compile(
    r'(authors\s*=\s*\[\{[^}]*?email\s*=\s*")([^"]*)(")',
    re.DOTALL,
)


def _pyproject_synced(text: str) -> str:
    def _sub(m: re.Match[str]) -> str:
        return f"{m.group(1)}{CANONICAL['maintainer_email']}{m.group(3)}"

    new_text, n = _AUTHOR_EMAIL_RE.subn(_sub, text)
    if n != 1:
        raise ContactDriftError(
            "pyproject.toml: expected exactly one [project].authors email to "
            f"sync, found {n} — refusing to guess (fail closed)"
        )
    return new_text


# ---------------------------------------------------------------------------
# SECURITY.md — bounded generated region.
# ---------------------------------------------------------------------------
_BEGIN = "<!-- BEGIN GENERATED: security_contact -->"
_END = "<!-- END GENERATED: security_contact -->"


def _security_block_body() -> str:
    return "\n".join(
        [
            f"Report security vulnerabilities privately to "
            f"**{CANONICAL['security_email']}**. Do not open a public issue or "
            "discussion for a security report.",
            "",
            "| Response stage | Target |",
            "| --- | --- |",
            f"| Acknowledgement | Within {CANONICAL['sla_acknowledgement']} |",
            f"| Initial assessment | Within {CANONICAL['sla_initial_assessment']} |",
            "",
            f"> **Legacy address.** `{CANONICAL['security_legacy_alias']}` remains "
            "a legacy compatibility alias. During the in-progress migration to "
            f"the canonical `{CANONICAL['security_email']}` identity, the legacy "
            "address continues to receive mail via Cloudflare Email Routing, so "
            "a report sent there still reaches us. The canonical mailbox is not "
            "yet live-sending.",
        ]
    )


def _security_synced(text: str) -> str:
    b = text.find(_BEGIN)
    e = text.find(_END)
    if b < 0 or e < 0 or e < b:
        raise ContactDriftError(
            f"SECURITY.md: bounded region not found — expected {_BEGIN!r} ... "
            f"{_END!r}"
        )
    before = text[: b + len(_BEGIN)]
    after = text[e:]
    return f"{before}\n{_security_block_body()}\n{after}"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def _consistency_guard() -> None:
    """Fail closed if the pinned facts are internally inconsistent."""
    if not CANONICAL["maintainer_email"].endswith("@agent-assembly.com"):
        raise ContactDriftError("pinned maintainer_email is not a .com address")
    if not CANONICAL["security_email"].endswith("@agent-assembly.com"):
        raise ContactDriftError("pinned security_email is not a .com address")
    if not CANONICAL["security_legacy_alias"].endswith("@agent-assembly.dev"):
        raise ContactDriftError("pinned legacy alias is not a .dev address")


def _targets(root: Path) -> dict[Path, str]:
    pyproject = root / "pyproject.toml"
    security = root / "SECURITY.md"
    return {
        pyproject: _pyproject_synced(pyproject.read_text(encoding="utf-8")),
        security: _security_synced(security.read_text(encoding="utf-8")),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if any consumer file drifts from the pinned registry.",
    )
    args = parser.parse_args(argv)

    root = _repo_root()
    try:
        _consistency_guard()
        targets = _targets(root)
    except (ContactDriftError, FileNotFoundError, OSError) as exc:
        print(f"ERROR: contact-metadata check failed — {exc}", file=sys.stderr)
        return 2

    drifted = [
        p for p, desired in targets.items() if p.read_text(encoding="utf-8") != desired
    ]
    if not drifted:
        print("Contact metadata is in sync with the pinned registry.")
        return 0

    if args.check:
        for p in drifted:
            print(f"DRIFT: {p.relative_to(root)} does not match the registry.", file=sys.stderr)
        print("Run: python scripts/check_contact_metadata.py", file=sys.stderr)
        return 1

    for p, desired in targets.items():
        if p in drifted:
            p.write_text(desired, encoding="utf-8")
            print(f"Wrote {p.relative_to(root)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
