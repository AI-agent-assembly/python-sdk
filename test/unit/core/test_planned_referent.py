"""AAASM-5750 — the ADR 0033 §6 ``Planned`` term must reference the ticket that
will build the capability, not the one that measured its absence.

§6 scopes ``Planned`` to "decided but not implemented — a ticket reference; no
capability claim." A reference to a ticket that never intended to deliver the
capability goes stale the moment that ticket closes: the term still reads as a
live commitment while the reference points at finished work. Nothing mechanical
catches that, because the referent lives in a comment or a docstring, and those
are the artifacts in a source tree with no check on them at all.

This is that check. It is deliberately a source scan rather than a review
convention — the previous referent was corrected by hand in three places here
and would have stayed correct only until the next edit.

The floor is a ratchet, not a transcription. It was measured from the tree when
this was written, and exists because an empty scan and a clean scan otherwise
report the same result.
"""

from __future__ import annotations

import re
from pathlib import Path

# The ticket that owns building the SDK-side audit sink.
CAPABILITY_REFERENT = "AAASM-5750"

# §6 Planned sites carrying a ticket reference when this gate was written.
# Fewer means sites were removed without revisiting this gate, which would leave
# it passing over nothing.
PLANNED_REFERENT_FLOOR = 3

_PLANNED_TERM = re.compile(r"\bPlanned\b")
_TICKET_REF = re.compile(r"AAASM-\d+")
_SCANNED_SUFFIXES = frozenset({".py", ".md"})
_SKIPPED_DIRS = frozenset({".git", ".venv", "node_modules", "__pycache__", "build", "dist"})


def _repo_root() -> Path:
    """Walk up to the directory holding ``pyproject.toml``.

    Resolving the root rather than assuming a relative path keeps the scan
    repository-wide regardless of the directory pytest is invoked from — a
    package-relative path silently narrows the scan to whatever happens to be
    below the caller.
    """
    for candidate in [Path(__file__).resolve(), *Path(__file__).resolve().parents]:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise AssertionError(
        "no pyproject.toml found above this test; the scan would cover nothing and pass for the wrong reason"
    )


def _planned_sites() -> list[tuple[str, int, str, str]]:
    """Every line where the §6 term and a ticket reference are co-located.

    A ``Planned`` with no ticket on the line is prose continuation, not a
    referent. Lowercase ``planned`` is ordinary English and is not the §6 term.
    """
    root = _repo_root()
    sites: list[tuple[str, int, str, str]] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in _SCANNED_SUFFIXES:
            continue
        if _SKIPPED_DIRS.intersection(path.relative_to(root).parts):
            continue

        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            if not _PLANNED_TERM.search(line):
                continue
            ticket = _TICKET_REF.search(line)
            if ticket is None:
                continue
            sites.append((str(path.relative_to(root)), lineno, ticket.group(0), line.strip()))

    return sites


def test_scan_reaches_the_planned_referent_sites() -> None:
    """Positive control on the scan itself.

    Without it, a walk that reached no files — a broken root, a changed suffix
    set, an over-broad skip list — reports the same clean result as a tree with
    every referent correct.
    """
    sites = _planned_sites()
    assert len(sites) >= PLANNED_REFERENT_FLOOR, (
        f"scan found {len(sites)} §6 Planned referent sites under {_repo_root()}, "
        f"floor is {PLANNED_REFERENT_FLOOR}; either sites were removed without "
        "revisiting this gate, or the scan stopped reaching them and is passing "
        "over nothing"
    )


def test_planned_references_the_capability_ticket() -> None:
    wrong = [site for site in _planned_sites() if site[2] != CAPABILITY_REFERENT]
    assert not wrong, "\n".join(
        f"{path}:{lineno} references {ticket} as the §6 Planned referent, want "
        f"{CAPABILITY_REFERENT} (the ticket that builds the sink, not one that "
        f"measured its absence): {text}"
        for path, lineno, ticket, text in wrong
    )
