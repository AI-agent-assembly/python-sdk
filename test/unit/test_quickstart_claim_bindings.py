"""Drift gate binding the quick-start's enforcement claims to the controls that prove them.

AAASM-5529, Epic AAASM-5526.

``docs/quick-start.md`` §"What just happened" is where the Python quick-start
tells a reader what governance did for them. Those sentences are the product's
load-bearing enforcement claims, and until now nothing connected them to the
negative controls in :mod:`test.unit.test_quickstart_negative_control`. A claim
could be added, reworded or left standing after the behaviour beneath it changed,
and no gate would notice.

What this gate proves
---------------------

#. **Every enforcement claim in the section is bound to a named control.** The
   claim list is parsed out of the document, so adding a fifth numbered claim
   without registering a binding for it fails here rather than shipping an
   unbacked sentence.
#. **Every binding still describes the document.** Each binding quotes the
   load-bearing fragment of its claim; rewording the sentence in the document
   breaks the quote and fails.
#. **Every control a binding names still exists.** The control names are
   extracted from the negative-control module's AST, not transcribed, so
   renaming or deleting a control fails here.
#. **Every SDK symbol the section names is real.** The symbol is imported and
   its ``__name__`` compared, so renaming ``ToolExecutionBlockedError`` in the
   SDK fails here instead of leaving the documentation pointing at a class that
   no longer exists.

What this gate does **not** prove
---------------------------------

It does not execute the quick-start, and it cannot: ``quickstart_snippets/`` is
a vendored, verbatim copy of regions from the ``examples`` repository
(``ruff.toml`` excludes it for this reason), and the snippets are partial
governance slices that reference names they never define — ``gateway_url``,
``api_key``, ``src.policy`` — so they are not importable modules. The existing
``quickstart-tabs-check`` workflow round-trips them as *text*, asserting only
that the generated document matches the vendored copy. Neither that gate nor
this one type-checks, imports or runs a snippet.

Nor does binding a claim make the claim *true*. A binding records which control
stands behind a sentence; where no control does, the binding must say so and
name the ticket, which is the state claim 1 is in today (AAASM-5661).
"""

from __future__ import annotations

import ast
import importlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# NOTE: the SDK symbols a claim names are resolved lazily, by module path and
# attribute name, rather than imported here. Importing them at module scope
# makes a rename a *collection* error, which aborts before
# test_named_sdk_symbols_resolve_to_that_name can run — leaving the assertion
# that is supposed to catch the rename permanently unexercised. That is the
# same inverted-order defect the round-1 review of this ticket found in all
# three SDKs, and it is invisible unless you mutate and watch which line fails.

_REPO_ROOT = Path(__file__).resolve().parents[2]
_QUICK_START = _REPO_ROOT / "docs" / "quick-start.md"
_NEGATIVE_CONTROL = Path(__file__).with_name("test_quickstart_negative_control.py")

_SECTION_HEADING = "## What just happened"

#: Claims that assert governance acted on a tool call. These are the ones the
#: Epic exists for, and the ones a binding must back with a control.
ENFORCEMENT = "enforcement"
#: Claims about setup or teardown. They are still bound, so the parser's
#: completeness check cannot be satisfied by silently dropping one, but they do
#: not require an enforcement control.
LIFECYCLE = "lifecycle"


@dataclass(frozen=True)
class ClaimBinding:
    """One documented claim and the controls that stand behind it."""

    claim_id: str
    kind: str
    #: A verbatim fragment of the claim as it appears in the document, with
    #: newlines collapsed. Rewording the document breaks this.
    quote: str
    #: ``ClassName::test_name`` node ids in the negative-control module.
    controls: tuple[str, ...] = ()
    #: Set when no control proves the claim. Must name the ticket that tracks it.
    unproven_reason: str = ""
    #: Backticked SDK identifiers the claim names, mapped to the module they
    #: must be importable from. Resolved lazily — see the note at the top.
    symbols: dict[str, str] = field(default_factory=dict)


BINDINGS: tuple[ClaimBinding, ...] = (
    ClaimBinding(
        claim_id="init-routes-every-tool-call",
        kind=ENFORCEMENT,
        quote="every tool call from this point on is routed",
        # Deliberately unbacked. AAASM-5661 measured the documented
        # configuration and found this sentence overstates it: the controls in
        # the negative-control module all call install_fake_core(), supplying an
        # authoritative runtime the documented configuration does not have, so
        # they are structurally incapable of proving a claim about the
        # documented path. Binding it to one of them would launder that gap into
        # evidence. The honest state is a named, ticketed absence.
        unproven_reason=(
            "AAASM-5661: the documented configuration was measured and no control "
            "covers it. Every control in test_quickstart_negative_control.py "
            "installs a fake native core, which the documented path does not have."
        ),
    ),
    ClaimBinding(
        claim_id="sdk-only-enforces-on-tool-calls",
        kind=ENFORCEMENT,
        quote="The in-process adapter enforces on tool calls with no",
        controls=(
            "TestFilesystemSideEffect::test_negative_control_denied_write_leaves_no_file",
            "TestNetworkSideEffect::test_negative_control_denied_egress_never_reaches_the_listener",
        ),
    ),
    ClaimBinding(
        claim_id="verdict-precedes-execution",
        kind=ENFORCEMENT,
        quote="asks the policy engine for an allow/deny verdict before the tool actually runs",
        # The two negative controls prove the *before* by absence of the side
        # effect; the two positive controls prove the probe would have seen the
        # effect had it happened. Both halves are named, because either alone is
        # the vacuous evidence this Epic exists to remove.
        controls=(
            "TestFilesystemSideEffect::test_positive_control_allowed_write_creates_the_file",
            "TestFilesystemSideEffect::test_negative_control_denied_write_leaves_no_file",
            "TestNetworkSideEffect::test_positive_control_allowed_egress_reaches_the_listener",
            "TestNetworkSideEffect::test_negative_control_denied_egress_never_reaches_the_listener",
        ),
    ),
    ClaimBinding(
        claim_id="with-block-unwinds",
        kind=LIFECYCLE,
        quote="tore everything down on exit",
        unproven_reason=(
            "Teardown is covered by the context-manager tests, not by the enforcement controls this gate binds."
        ),
    ),
    ClaimBinding(
        claim_id="deny-surfaces-as-tool-execution-blocked",
        kind=ENFORCEMENT,
        quote="that is not a bug — the policy denied the",
        controls=(
            "TestFilesystemSideEffect::test_negative_control_denied_write_leaves_no_file",
            "TestDegradedRuntimeCannotLookProtected"
            "::test_an_unavailable_native_runtime_denies_rather_than_silently_allowing",
        ),
        symbols={"ToolExecutionBlockedError": "agent_assembly.exceptions"},
    ),
)


def _section_text() -> str:
    """Return the "What just happened" section, up to the next ``##`` heading."""
    document = _QUICK_START.read_text(encoding="utf-8")
    start = document.find(_SECTION_HEADING)
    assert start != -1, (
        f"{_QUICK_START} no longer contains a '{_SECTION_HEADING}' section. "
        "If the quick-start was restructured, re-point this gate at the section "
        "that now carries the enforcement claims — do not delete it."
    )
    body = document[start + len(_SECTION_HEADING) :]
    end = body.find("\n## ")
    return body if end == -1 else body[:end]


def _flatten(text: str) -> str:
    """Collapse Markdown's soft wrapping so a quote can span wrapped lines."""
    return re.sub(r"\s+", " ", text).strip()


def _documented_claims() -> dict[str, str]:
    """Parse the section into ``claim_key -> flattened text``.

    Numbered list items become ``item-N``; the trailing prose paragraph becomes
    ``prose-N``. Both are derived from the document, so a newly added claim
    appears here without anyone updating this module — which is the point.
    """
    section = _section_text()
    claims: dict[str, str] = {}

    # Numbered items: "1. ..." through the line before the next "N. " or a blank
    # line followed by unindented prose.
    item_pattern = re.compile(r"^(\d+)\.\s+(.*(?:\n(?![ ]*\d+\.\s|\n).*)*)", re.MULTILINE)
    for match in item_pattern.finditer(section):
        claims[f"item-{match.group(1)}"] = _flatten(match.group(2))

    # Prose paragraphs that make a claim, i.e. mention denial or blocking. Link
    # lists and prose that merely points elsewhere are not claims.
    consumed = {match.group(0) for match in item_pattern.finditer(section)}
    remainder = section
    for chunk in consumed:
        remainder = remainder.replace(chunk, "\n")
    for index, paragraph in enumerate(p for p in remainder.split("\n\n") if p.strip()):
        flat = _flatten(paragraph)
        if re.search(r"\bdenied\b|\bblocked\b|\bdeny\b", flat, re.IGNORECASE):
            claims[f"prose-{index}"] = flat

    return claims


def _control_node_ids() -> set[str]:
    """Extract ``ClassName::test_name`` ids from the negative-control module's AST.

    Derived from the source rather than transcribed, so this set changes when a
    control is renamed or removed and the bindings above then fail.
    """
    tree = ast.parse(_NEGATIVE_CONTROL.read_text(encoding="utf-8"))
    node_ids: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) and child.name.startswith("test_"):
                    node_ids.add(f"{node.name}::{child.name}")
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test_"):
            node_ids.add(node.name)
    return node_ids


class TestTheGateCanSeeWhatItGates:
    """Positive controls. Every check below reads a real artifact; prove it arrived."""

    def test_the_quick_start_section_is_found_and_non_empty(self) -> None:
        section = _section_text()
        assert len(section.strip()) > 200, "the parsed section is too short to contain the claim list"

    def test_the_parser_finds_the_numbered_claims(self) -> None:
        claims = _documented_claims()
        numbered = [key for key in claims if key.startswith("item-")]
        # A count is asserted, not a list, because the list is the thing under
        # test. If the document grows a claim this fails, which is the gate.
        assert len(numbered) >= 4, f"expected the four documented claims, parsed {sorted(claims)}"

    def test_the_ast_extraction_finds_the_negative_controls(self) -> None:
        node_ids = _control_node_ids()
        assert len(node_ids) >= 8, f"AST extraction found only {len(node_ids)} controls: {sorted(node_ids)}"
        # A named one, so an extraction that silently returned an unrelated set
        # cannot satisfy the count above.
        assert "TestFilesystemSideEffect::test_negative_control_denied_write_leaves_no_file" in node_ids


class TestEveryDocumentedClaimIsBound:
    def test_no_claim_in_the_section_is_unbound(self) -> None:
        """Adding a claim to the quick-start without a binding fails here.

        This is the check that makes the gate load-bearing rather than
        decorative: a new enforcement sentence cannot reach the published
        quick-start without someone naming the control that stands behind it,
        or recording in the binding that none does.
        """
        documented = _documented_claims()
        unmatched = {
            key: text for key, text in documented.items() if not any(binding.quote in text for binding in BINDINGS)
        }
        assert not unmatched, (
            "These quick-start claims have no ClaimBinding in BINDINGS:\n"
            + "\n".join(f"  {key}: {text}" for key, text in unmatched.items())
            + "\n\nAdd a ClaimBinding naming the control that proves each one. If no "
            "control does, set unproven_reason and name the ticket — do not delete "
            "the claim from this gate to make it pass."
        )

    @pytest.mark.parametrize("binding", BINDINGS, ids=lambda b: b.claim_id)
    def test_each_binding_still_quotes_the_document(self, binding: ClaimBinding) -> None:
        """Rewording a claim in the document fails here."""
        documented = _documented_claims()
        assert any(binding.quote in text for text in documented.values()), (
            f"ClaimBinding {binding.claim_id!r} quotes:\n  {binding.quote!r}\n"
            f"which no longer appears in {_SECTION_HEADING!r} of {_QUICK_START.name}. "
            "The claim was reworded or removed. Update the quote and re-check that "
            "the named controls still prove the new wording."
        )


class TestEveryBindingNamesSomethingReal:
    @pytest.mark.parametrize("binding", BINDINGS, ids=lambda b: b.claim_id)
    def test_named_controls_exist(self, binding: ClaimBinding) -> None:
        """Renaming or deleting a control fails here."""
        available = _control_node_ids()
        missing = [control for control in binding.controls if control not in available]
        assert not missing, (
            f"ClaimBinding {binding.claim_id!r} names controls that do not exist in "
            f"{_NEGATIVE_CONTROL.name}: {missing}\n"
            "The control was renamed or removed. Re-point the binding at the control "
            "that now proves the claim, or mark the claim unproven and name the ticket."
        )

    @pytest.mark.parametrize("binding", BINDINGS, ids=lambda b: b.claim_id)
    def test_an_enforcement_claim_is_either_proven_or_openly_unproven(self, binding: ClaimBinding) -> None:
        """An enforcement claim may not be silently unbacked."""
        if binding.kind != ENFORCEMENT:
            return
        assert binding.controls or binding.unproven_reason, (
            f"Enforcement claim {binding.claim_id!r} names no control and gives no "
            "unproven_reason. One or the other is required: a documented enforcement "
            "claim with neither is exactly the unbacked assertion AAASM-5526 exists "
            "to eliminate."
        )
        if not binding.controls:
            assert re.search(r"AAASM-\d+", binding.unproven_reason), (
                f"Claim {binding.claim_id!r} is unproven but its reason names no "
                "ticket. An unproven claim must be traceable to the work that "
                f"resolves it. Reason given: {binding.unproven_reason!r}"
            )

    @pytest.mark.parametrize("binding", BINDINGS, ids=lambda b: b.claim_id)
    def test_named_sdk_symbols_resolve_to_that_name(self, binding: ClaimBinding) -> None:
        """Renaming an SDK class the document names fails here."""
        for documented_name, module_path in binding.symbols.items():
            module = importlib.import_module(module_path)
            resolved = getattr(module, documented_name, None)
            assert resolved is not None, (
                f"{_QUICK_START.name} names `{documented_name}` but that symbol no "
                f"longer exists in {module_path}. The class was renamed or moved, so "
                "the documented quick-start now points at something a reader cannot "
                "import. Update the documentation and this binding together."
            )
            assert resolved.__name__ == documented_name, (
                f"{_QUICK_START.name} names {documented_name!r} but the resolved "
                f"symbol reports __name__ == {resolved.__name__!r} — the documented "
                "name is an alias for a class that has been renamed underneath it."
            )
            assert f"`{documented_name}`" in _section_text(), (
                f"ClaimBinding {binding.claim_id!r} declares the symbol "
                f"{documented_name!r} but the section no longer mentions it."
            )
