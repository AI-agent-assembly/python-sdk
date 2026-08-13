"""AAASM-5750 — AAASM-5731 must not be the referent of a forward-looking claim.

The rule this gate enforces comes from **AAASM-5750's own description**, not from
ADR 0033 §6. §6 requires that ``Planned`` carry *a* ticket reference and says
nothing about which ticket; naming the right one is 5750's decision. Stating the
source precisely matters, because a failure message citing an ADR for a rule the
ADR does not contain sends the next reader to the wrong document.

The defect: AAASM-5731 measured that no interceptor this SDK ships resolves an
audit hook. It never intended to build a sink, and it is closed. A
forward-looking claim pointing at it reads as a live commitment while resolving
to finished work. So the invariant is narrow and permanent — **AAASM-5731 may be
cited as the ticket that measured the gap, never as the ticket that will fix
it.**

Deliberately NOT asserted: that every ``Planned`` in this repository names
AAASM-5750. §6 scopes ``Planned`` to any decided-but-unbuilt capability with any
ticket, so an unrelated roadmap row — including
``docs/examples/framework-support.md``'s docs-area maturity label, a different
axis entirely — is legitimate and must not fail this gate. The first version of
this test made exactly that over-broad assertion.
"""

from __future__ import annotations

import re
from pathlib import Path

#: Tickets that *measured* the absence of an SDK-side audit sink. Backward
#: citations to them are correct and are left alone; what this gate forbids is
#: either one appearing as the ticket a forward-looking claim defers to.
STALE_REFERENTS = frozenset({"AAASM-5731", "AAASM-5681"})

#: The two shapes a deferral takes: the ADR 0033 §6 term, and the plain
#: "tracked as" pointer used where no term is stated.
_FORWARD_CLAIM = re.compile(r"\bPlanned\b|tracked as")
_TICKET_REF = re.compile(r"AAASM-\d+")
_SCANNED_SUFFIXES = frozenset({".py", ".md"})
_SKIPPED_DIRS = frozenset({".git", ".venv", "node_modules", "__pycache__", "build", "dist"})

#: Excluded from its own scan. Including it was the first version's defect: this
#: file names AAASM-5750 in its own docstring, which padded the site count and
#: let a floor be satisfied by the gate quoting itself.
_GATE_FILE = "test/unit/core/test_planned_referent.py"

#: Audit-sink deferrals that must remain reachable by the scan. A fixture
#: compared against a walk of the tree, not a constant compared against another
#: constant: if a site is deleted, renamed, or reflowed out of the scan's reach,
#: the walk stops finding it and this fails.
EXPECTED_SITES = (
    "agent_assembly/core/audit_sink.py",
    "agent_assembly/adapters/_shared/tool_governance.py",
    "test/unit/test_quickstart_negative_control.py",
)


def _repo_root() -> Path:
    """Walk up to the directory holding ``pyproject.toml``.

    Resolving the root rather than assuming a relative path keeps the scan
    repository-wide regardless of the directory pytest is invoked from — a
    package-relative path silently narrows the scan to whatever is below the
    caller.
    """
    for candidate in [Path(__file__).resolve(), *Path(__file__).resolve().parents]:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise AssertionError(
        "no pyproject.toml found above this test; the scan would cover nothing and pass for the wrong reason"
    )


def _deferral_sites() -> list[tuple[str, int, str, str]]:
    """Every forward-looking claim paired with a ticket.

    The ticket is looked for on the claim's own line **and the line after it**.
    One line is not enough: ``test/unit/test_quickstart_negative_control.py``
    wraps ``Planned`` and its ticket onto separate lines, and the first version
    of this scan silently skipped it while the PR claimed it was covered.
    Whether a site is checked must not depend on where a comment happens to
    wrap.
    """
    root = _repo_root()
    sites: list[tuple[str, int, str, str]] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in _SCANNED_SUFFIXES:
            continue

        rel = path.relative_to(root)
        if _SKIPPED_DIRS.intersection(rel.parts) or str(rel) == _GATE_FILE:
            continue

        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for index, line in enumerate(lines):
            if not _FORWARD_CLAIM.search(line):
                continue

            window = line
            if index + 1 < len(lines):
                window = f"{line}\n{lines[index + 1]}"

            ticket = _TICKET_REF.search(window)
            if ticket is None:
                continue

            sites.append((str(rel), index + 1, ticket.group(0), line.strip()))

    return sites


def test_no_forward_claim_defers_to_a_closed_measurement_ticket() -> None:
    wrong = [site for site in _deferral_sites() if site[2] in STALE_REFERENTS]
    assert not wrong, "\n".join(
        f"{path}:{lineno} defers to {ticket}, which measured the gap and will "
        f"not fix it — use the ticket that builds the sink (AAASM-5750, per its "
        f"own description): {text}"
        for path, lineno, ticket, text in wrong
    )


def test_every_expected_site_is_still_reachable() -> None:
    """Anti-vacuity, and the reason it names paths rather than counting.

    A count can be held up by an unrelated site appearing as a real one is
    deleted. Naming them makes that substitution visible.
    """
    seen = {site[0] for site in _deferral_sites()}
    missing = [path for path in EXPECTED_SITES if path not in seen]
    assert not missing, "\n".join(
        f"{path} carries no forward claim the scan can pair with a ticket; it "
        f"was deleted, renamed, or reflowed so the term and the ticket are more "
        f"than one line apart — in which case a stale referent there would no "
        f"longer be checked"
        for path in missing
    )
