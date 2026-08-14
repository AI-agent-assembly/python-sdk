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

**AAASM-5750 built the sink, so it joined the list it used to be the answer
to.** This gate previously required a fixed set of guarded files to name
AAASM-5750 as the ticket their ``Planned`` deferred to. Once the capability
exists there is nothing left to defer: a site still calling SDK-side recording
*Planned* under AAASM-5750 describes shipped behaviour as unbuilt, which is the
same stale-pointer defect one ticket later. So the rule collapsed to a single
tier — **no forward-looking claim in this repository may defer SDK-side audit
recording to any of the three tickets that are done with it** — and applies
repository-wide rather than to a named set.

§6 still scopes ``Planned`` to any decided-but-unbuilt capability with any
ticket, so an unrelated roadmap row — including
``docs/examples/framework-support.md``'s docs-area maturity label, a different
axis entirely — is legitimate and must not fail this gate. Only the three named
referents are forbidden.

A rule whose expected result is "no findings" needs the scan proved reachable, or
a broken walk passes as loudly as a clean tree.
:func:`test_the_deferral_scan_can_see` feeds the detector synthetic lines
carrying exactly the shapes this file forbids and requires it to find them. The
empty result is meaningful only because that control is green.

One limit is disclosed rather than fixed: the gate file is excluded from its own
scan, so it is a hiding place for a stale referent. It is a test file that
documents no SDK behaviour, and the exclusion matches one exact path rather than
a prefix.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

#: Tickets a forward-looking claim about SDK-side audit recording may no longer
#: defer to. Backward citations to any of them are correct and are left alone;
#: what this gate forbids is one of them appearing as the ticket a *deferral*
#: points at. The reason differs per entry, and the failure message says which.
STALE_REFERENTS = {
    "AAASM-5731": "measured the gap and never intended to fix it",
    "AAASM-5681": "measured the gap and never intended to fix it",
    "AAASM-5750": "built the sink; SDK-side recording is no longer deferred",
}

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


def _ends_sentence(line: str) -> bool:
    """Whether a comment line closes a sentence.

    A wrapped sentence (``… Planned under ADR 0033 §6`` / ``(AAASM-5750) …``)
    does not; a complete one does.
    """
    trimmed = line.strip().rstrip("#* ")
    return bool(trimmed) and trimmed[-1] in ".!?"


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
        sites.extend(deferrals_in_lines(str(rel), lines))

    return sites


def deferrals_in_lines(path: str, lines: list[str]) -> list[tuple[str, int, str, str]]:
    """The detector, split out from the walk.

    Separated so a control can drive it over input it constructs rather than over
    whatever the tree happens to contain: a gate whose expected result is
    "nothing found" is only as good as the proof that it can find something.
    """
    sites: list[tuple[str, int, str, str]] = []
    for index, line in enumerate(lines):
        if not _FORWARD_CLAIM.search(line):
            continue

        # Extend to the next line only when this line carries no ticket of its
        # own AND does not end a sentence. Without the sentence guard the window
        # pairs a claim with a ticket belonging to the *next* sentence — review
        # produced a real case where an inserted line of forward-looking prose
        # was blamed for a correct backward citation beneath it. There are 33
        # such backward citations in this repo.
        window = line
        if not _TICKET_REF.search(line) and not _ends_sentence(line) and index + 1 < len(lines):
            window = f"{line}\n{lines[index + 1]}"

        ticket = _TICKET_REF.search(window)
        if ticket is None:
            continue

        sites.append((path, index + 1, ticket.group(0), line.strip()))
    return sites


def test_no_forward_claim_defers_to_a_finished_ticket() -> None:
    problems = [
        f"{path}:{lineno} defers to {ticket}, which {STALE_REFERENTS[ticket]} — a "
        f"forward-looking claim must not point at it: {text}"
        for path, lineno, ticket, text in _deferral_sites()
        if ticket in STALE_REFERENTS
    ]
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize(
    ("lines", "ticket"),
    [
        (["# recording here is Planned (AAASM-5731), not Observed."], "AAASM-5731"),
        (
            [
                "# Under ADR 0033 section 6 SDK-side recording is Planned",
                "# (AAASM-5750), not Observed.",
            ],
            "AAASM-5750",
        ),
        (["# Wiring a sink that retains it is tracked as AAASM-5681."], "AAASM-5681"),
    ],
    ids=["one line", "wrapped onto two lines", "termless 'tracked as'"],
)
def test_the_deferral_scan_can_see(lines: list[str], ticket: str) -> None:
    """Positive control for the assertion above.

    That assertion expects to find nothing, and every way of breaking the scan —
    a regex that stops matching, a walk that reaches no files, a window that
    never extends across a wrapped comment — produces exactly the same green. So
    the detector is fed input containing each shape it is supposed to catch and
    required to catch it. If it stops seeing these, the repository-wide silence
    stops meaning anything.
    """
    found = deferrals_in_lines("synthetic.py", lines)
    assert len(found) == 1 and found[0][2] == ticket, (
        f"the detector found {found} in {lines}; it must find exactly one deferral naming "
        f"{ticket}, or the repository-wide empty result proves nothing"
    )
    assert ticket in STALE_REFERENTS, f"{ticket} is not forbidden, so this control could not fail the gate"


def test_an_unrelated_open_deferral_is_detected_and_permitted() -> None:
    """The other direction: the gate must not forbid every ticket.

    Without this it could pass by rejecting all deferrals, which would push
    authors to drop the ticket reference §6 requires rather than to fix the
    referent.
    """
    found = deferrals_in_lines("synthetic.py", ["# A curated example is Planned (AAASM-9999)."])
    assert len(found) == 1, f"the detector missed an unrelated roadmap deferral: {found}"
    assert found[0][2] not in STALE_REFERENTS
