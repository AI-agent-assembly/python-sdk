#!/usr/bin/env python3
"""Audit the README sample-output version literal against the package SoT.

WHY THIS EXISTS
---------------
Per ADR 0013 (version-metadata source-of-truth & drift gate, AAASM-4907), every
version-bearing value has exactly one source of truth and nothing outside it may
carry a drifting version literal. This repo's SoT is the package version anchor in
``pyproject.toml`` (``[project].version``); ``release-tag-cut`` is its only
sanctioned writer.

``README.md`` shows a ``aasm --version`` sample whose expected output (``# e.g.
aasm <version>``) is a hand-typed literal that sits outside that anchor — tag [B]
in the ADR's audit (Appendix A / Appendix B item 4). It stays correct only by a
maintainer remembering to retype it on every bump, which is exactly the drift the
ADR eliminates.

Rather than stand up a full generator/metadata pipeline for a single line, this is
the ADR's alternative: a scoped **orphan-literal audit**. It reads the anchor and
fails if any ``aasm <version>`` sample literal in the README does not equal it, so a
stale sample output is a red build at PR time instead of a finding in a later sweep.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

# Matches a sample-output CLI version token: the literal ``aasm`` followed by a
# version starting with a digit (so ``aasm --version`` and prose like ``aasm CLI``
# are not captured — only the emitted ``aasm 0.0.1rc6`` form).
_SAMPLE_VERSION = re.compile(r"\baasm\s+(\d[\w.+-]*)")


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def read_anchor(pyproject: Path) -> str:
    """Return the package version anchor (the SoT) from ``pyproject.toml``."""
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    version = data["project"]["version"]
    if not isinstance(version, str):  # pragma: no cover - malformed manifest
        raise TypeError(f"[project].version is not a string: {version!r}")
    return version


def find_sample_versions(readme_text: str) -> list[str]:
    """Return every ``aasm <version>`` sample-output literal found in the README."""
    return _SAMPLE_VERSION.findall(readme_text)


def audit(pyproject: Path, readme: Path) -> list[str]:
    """Return a list of drift messages; empty means the README is in sync."""
    anchor = read_anchor(pyproject)
    found = find_sample_versions(readme.read_text(encoding="utf-8"))
    return [
        f"{readme.name}: sample output 'aasm {literal}' drifted from the pyproject.toml version anchor 'aasm {anchor}'"
        for literal in found
        if literal != anchor
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Audit only and exit non-zero on drift (the CI-gate mode).",
    )
    parser.parse_args(argv)

    root = _repo_root()
    drift = audit(root / "pyproject.toml", root / "README.md")
    if drift:
        for message in drift:
            print(f"error: {message}", file=sys.stderr)
        print(
            "\nThe README sample output must match the pyproject.toml version "
            "anchor (SoT). Edit the anchor, not the README literal, then update "
            "the README sample to match. See ADR 0013.",
            file=sys.stderr,
        )
        return 1
    print("README sample-output version is in sync with the pyproject.toml anchor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
