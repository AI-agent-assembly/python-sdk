"""Drift gate binding the quick-start's enforcement claims to the controls that prove them.

AAASM-5529, Epic AAASM-5526.

``docs/quick-start.md`` tells a reader what governance did for them. Those
sentences are the product's load-bearing enforcement claims, and until now
nothing connected them to the negative controls in
:mod:`test.unit.test_quickstart_negative_control`. A claim could be added,
reworded, or left standing after the behaviour beneath it changed, and no gate
would notice.

What this gate proves
---------------------

#. **The whole document is scanned, not an opted-in section.** Every sentence
   that uses enforcement vocabulary anywhere in the quick-start must be bound.
   Regions and sentences may be excluded only through the two named allow-lists
   below, each entry carrying a reason and an exact sentence — so an allow-list
   entry cannot cover a reworded or newly added claim.
#. **A binding must match a whole sentence, exactly.** ``quote`` is compared
   with ``==`` against the flattened sentence, never with ``in``. Substring
   containment let a sentence carry unlimited extra unbound claims — including
   its own negation — as long as one bound fragment survived, which is the
   defect this revision exists to close.
#. **Exactly one binding may match a sentence,** so two bindings cannot quietly
   split responsibility for one claim and leave neither owning it.
#. **Every control a binding names still exists.** Control names are extracted
   from the negative-control module's AST, not transcribed, so renaming or
   deleting one fails here.
#. **Every claim is proven or openly unproven.** There is no claim category
   exempt from that: a binding names controls, or names a ticket. The former
   ``kind`` field was removed because it was a one-word bypass — relabelling a
   claim as lifecycle disabled the requirement entirely.
#. **Every SDK symbol the document names is real,** resolved lazily so a rename
   fails on the assertion rather than aborting collection.

What this gate does **not** prove
---------------------------------

It does not execute the quick-start, and it cannot: ``quickstart_snippets/`` is
a vendored, verbatim copy of regions from the ``examples`` repository
(``ruff.toml`` excludes it for this reason), and the snippets are partial
governance slices that reference names they never define — ``gateway_url``,
``api_key``, ``src.policy`` — so they are not importable modules. The existing
``quickstart-tabs-check`` drift job round-trips them as *text*, asserting only
that the generated document matches the vendored copy. Neither that job nor
this one type-checks, imports or runs a snippet.

Nor does binding a claim make the claim *true*. A binding records which control
stands behind a sentence; where none does, the binding must say so and name the
ticket.
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
# that is supposed to catch the rename permanently unexercised.

_REPO_ROOT = Path(__file__).resolve().parents[2]
_QUICK_START = _REPO_ROOT / "docs" / "quick-start.md"
_NEGATIVE_CONTROL = Path(__file__).with_name("test_quickstart_negative_control.py")

#: Sentences using any of these make a claim about what governance does. Kept
#: deliberately wide: a narrow vocabulary is itself a bypass, because a new
#: enforcement paragraph phrased around it is not treated as a claim at all.
_ENFORCEMENT_VOCABULARY = re.compile(
    r"(?i)\bdenie[sd]\b|\bdeny\b|\bblocked\b|\bblocking\b|\bnever runs?\b"
    r"|\bbefore execution\b|\bchecked against\b|\benforces?\b|\benforced\b"
    r"|\bpassthrough\b|\bdiscards?\b|\bdiscarded\b|\bthrows?\b|\brejects?\b"
    r"|\brouted\b|\bintercepts?\b|\binterception\b|\bgoverned\b|\bverified\b"
    r"|\bprotection\b|\bunprotected\b|\bbypass(ed|es)?\b"
)

#: Whole sections excluded from the scan, each with the reason. Keyed by the
#: exact heading line.
_EXCLUDED_SECTIONS: dict[str, str] = {
    "## Next steps": (
        "A link list. Every line is a cross-reference to another page; the "
        "claims themselves live on the pages linked to and are gated there."
    ),
}

#: Individual sentences excluded from the scan, each with the reason. These are
#: exact flattened sentences, never patterns, so an entry cannot silently cover
#: a reworded or newly added claim — changing the sentence makes the entry stale
#: and test_every_excluded_sentence_is_still_present_verbatim fails.
_EXCLUDED_SENTENCES: dict[str, str] = {
    "See [Handling allow/deny decisions](guides/handling-decisions.md) for how to catch and respond to "
    "those, and [Troubleshooting](troubleshooting.md) if `init_assembly()` itself raised.": (
        "Navigational cross-reference. It makes no capability claim of its "
        "own; it matches the vocabulary only through the linked page's title."
    ),
}


@dataclass(frozen=True)
class ClaimBinding:
    """One documented claim and the controls that stand behind it."""

    claim_id: str
    #: The claim as a WHOLE sentence, flattened. Compared with ==, not `in`.
    quote: str
    #: ``ClassName::test_name`` node ids in the negative-control module.
    controls: tuple[str, ...] = ()
    #: Set when no control proves the claim. Must name the ticket that tracks it.
    unproven_reason: str = ""
    #: Backticked SDK identifiers the claim names, mapped to the module they
    #: must be importable from. Resolved lazily.
    symbols: dict[str, str] = field(default_factory=dict)


_DENY_CONTROLS = (
    "TestFilesystemSideEffect::test_negative_control_denied_write_leaves_no_file",
    "TestNetworkSideEffect::test_negative_control_denied_egress_never_reaches_the_listener",
)
_ALLOW_AND_DENY_CONTROLS = (
    "TestFilesystemSideEffect::test_positive_control_allowed_write_creates_the_file",
    "TestFilesystemSideEffect::test_negative_control_denied_write_leaves_no_file",
    "TestNetworkSideEffect::test_positive_control_allowed_egress_reaches_the_listener",
    "TestNetworkSideEffect::test_negative_control_denied_egress_never_reaches_the_listener",
)

BINDINGS: tuple[ClaimBinding, ...] = (
    ClaimBinding(
        claim_id="gateway-returns-allow-deny-decisions",
        quote=("`init_assembly()` needs to reach a **gateway** — the policy brain that returns allow/deny decisions."),
        # AAASM-5661 measured the documented configuration: it reaches no
        # gateway and installs a deny-all fail-closed interceptor instead. No
        # control covers the documented path, because every control here
        # supplies a fake native core the documented path does not have.
        unproven_reason=(
            "AAASM-5661: the documented configuration was measured and reaches no gateway. "
            "Every control in test_quickstart_negative_control.py installs a fake native "
            "core, so none of them exercises the path this sentence describes."
        ),
    ),
    ClaimBinding(
        claim_id="init-routes-every-tool-call",
        quote=(
            "**`init_assembly()` wired in governance.** It registered the agent with the gateway "
            "and auto-loaded the adapter for your framework — every tool call from this point on "
            "is routed through the policy gate."
        ),
        unproven_reason=(
            "AAASM-5661: measured false for the documented configuration. Binding this to a "
            "control that installs a fake native core would launder that gap into evidence."
        ),
    ),
    ClaimBinding(
        claim_id="sdk-only-enforces-on-tool-calls",
        quote=(
            '**`mode="sdk-only"` kept it offline.** The in-process adapter enforces on tool calls '
            "with no network sidecar, so the example runs deterministically with no real LLM or "
            "gateway round-trip."
        ),
        controls=_DENY_CONTROLS,
    ),
    ClaimBinding(
        claim_id="verdict-precedes-execution",
        quote=(
            "**Tool calls were governed.** The adapter intercepts the framework's tool-invocation "
            "path and asks the policy engine for an allow/deny verdict before the tool actually "
            "runs."
        ),
        # Both halves are named. The negative controls prove the "before" by
        # absence of the side effect; the positive controls prove the probe
        # would have seen that effect had it happened. Either alone is the
        # vacuous evidence this Epic exists to remove.
        controls=_ALLOW_AND_DENY_CONTROLS,
    ),
    ClaimBinding(
        claim_id="deny-surfaces-as-tool-execution-blocked",
        quote=("If a tool call raises a `ToolExecutionBlockedError`, that is not a bug — the policy denied the call."),
        controls=(
            *_DENY_CONTROLS,
            "TestDegradedRuntimeCannotLookProtected"
            "::test_an_unavailable_native_runtime_denies_rather_than_silently_allowing",
        ),
        symbols={"ToolExecutionBlockedError": "agent_assembly.exceptions"},
    ),
    ClaimBinding(
        claim_id="sdk-only-is-the-in-process-interception-layer",
        quote=(
            '`mode="sdk-only"` is the in-process-only interception layer: the framework adapter '
            "enforces on tool calls, with no network sidecar to start."
        ),
        controls=_DENY_CONTROLS,
    ),
    ClaimBinding(
        claim_id="other-modes-add-network-kernel-interception",
        quote=(
            "The other modes (`auto`, `proxy`, `ebpf`) add network/kernel interception — see "
            "[Core Concepts → Modes](concepts/index.md#runtime-modes)."
        ),
        # This is the sentence AAASM-5529's own SDK-specific check names:
        # "mode=auto/proxy/ebpf does not report verified network protection
        # unless the corresponding layer is actually running and probed." No
        # control in this repo probes a proxy or eBPF layer, so the claim rests
        # on the Core Concepts page's authority, not on evidence here.
        unproven_reason=(
            "AAASM-5529: this ticket's own mode-probing acceptance check is not delivered. "
            "No control in the Python SDK starts or probes a proxy or eBPF layer, so nothing "
            "here can distinguish 'the mode adds interception' from 'the mode is selected'."
        ),
    ),
)


def _document() -> str:
    """Read the quick-start with line endings normalised to LF.

    Without this the paragraph split never fires on a CRLF checkout: the whole
    section collapses into one "sentence" that matches no binding. Node's four
    Windows CI legs caught exactly that while Linux and macOS stayed green.
    This repo's CI is Linux-only, so the bug is latent here — normalised anyway,
    because a gate whose result depends on the checkout's line endings is not a
    gate.
    """
    return _QUICK_START.read_text(encoding="utf-8").replace("\r\n", "\n")


def _flatten(text: str) -> str:
    """Collapse Markdown's soft wrapping so a sentence is one line."""
    return re.sub(r"\s+", " ", text).strip()


def _scanned_sentences() -> dict[str, str]:
    """Return ``flattened sentence -> section heading`` for the whole document.

    Fenced code is dropped, and sections named in :data:`_EXCLUDED_SECTIONS` are
    skipped. Everything else is in scope — the gate opts sections *out* by name
    rather than opting them in, so a claim added to a section nobody thought
    about is still caught.
    """
    # A fenced block becomes a PARAGRAPH break, not a space. Replacing it with a
    # space glued the sentence before a code sample to the sentence after it —
    # 18 such pairs in this document — and a binding quoting the glued pair
    # would then cover two claims at once, which is fragment containment one
    # level up.
    body = re.sub(r"```.*?```", "\n\n", _document(), flags=re.DOTALL)

    sentences: dict[str, str] = {}
    section = "(preamble)"
    for chunk in re.split(r"(?m)^(#{2,6} .*)$", body):
        if chunk is None:
            continue
        if re.match(r"^#{2,6} ", chunk):
            section = chunk.strip()
            continue
        if section in _EXCLUDED_SECTIONS:
            continue
        for paragraph in chunk.split("\n\n"):
            for raw in re.split(r"(?<=\.)\s+", paragraph):
                flat = _flatten(raw)
                if flat:
                    sentences[flat] = section
    return sentences


def _claim_sentences() -> dict[str, str]:
    """The scanned sentences that make an enforcement claim, minus the allow-list."""
    return {
        sentence: section
        for sentence, section in _scanned_sentences().items()
        if _ENFORCEMENT_VOCABULARY.search(sentence) and sentence not in _EXCLUDED_SENTENCES
    }


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
    """Positive controls. Every check below reads a real artifact; prove it arrived.

    An empty parse and a clean result are otherwise indistinguishable, which is
    the failure mode that makes a drift gate worthless without ever going red.
    """

    def test_the_document_is_read_and_split_into_sentences(self) -> None:
        sentences = _scanned_sentences()
        assert len(sentences) > 40, f"only {len(sentences)} sentences parsed from the whole quick-start"

    def test_the_scan_finds_enforcement_claims(self) -> None:
        claims = _claim_sentences()
        assert len(claims) >= 7, f"only {len(claims)} claim sentences found: {sorted(claims)}"

    def test_the_scan_reaches_beyond_the_what_just_happened_section(self) -> None:
        """The whole document is in scope, not one opted-in region.

        Without this, narrowing the scan back to a single section would look
        identical to a clean pass.
        """
        sections = set(_claim_sentences().values())
        assert len(sections) >= 3, f"claims were found in only these sections: {sections}"

    def test_the_ast_extraction_finds_the_negative_controls(self) -> None:
        node_ids = _control_node_ids()
        assert len(node_ids) >= 8, f"AST extraction found only {len(node_ids)} controls: {sorted(node_ids)}"
        assert "TestFilesystemSideEffect::test_negative_control_denied_write_leaves_no_file" in node_ids


class TestTheAllowListCannotBecomeABypass:
    def test_every_excluded_section_is_still_a_real_heading(self) -> None:
        document = _document()
        for heading, reason in _EXCLUDED_SECTIONS.items():
            assert heading in document, (
                f"_EXCLUDED_SECTIONS names {heading!r}, which is no longer a heading in "
                f"{_QUICK_START.name}. A stale exclusion silently widens over time — remove it."
            )
            assert reason.strip(), f"exclusion {heading!r} carries no reason"

    def test_every_excluded_sentence_is_still_present_verbatim(self) -> None:
        """An allow-listed sentence must still exist, exactly.

        This is what stops the allow-list becoming the new bypass: an entry is a
        whole sentence, so rewording the claim makes the entry stale and fails
        here rather than silently exempting the new wording.
        """
        scanned = _scanned_sentences()
        for sentence, reason in _EXCLUDED_SENTENCES.items():
            assert sentence in scanned, (
                f"_EXCLUDED_SENTENCES contains a sentence that no longer appears in "
                f"{_QUICK_START.name}:\n  {sentence!r}\n"
                "It was reworded or removed. Delete the stale entry, and if the replacement "
                "makes an enforcement claim, bind it."
            )
            assert reason.strip(), f"exclusion of {sentence!r} carries no reason"


class TestEveryDocumentedClaimIsBound:
    def test_no_enforcement_sentence_is_unbound(self) -> None:
        """Adding an enforcement claim anywhere in the quick-start fails here.

        This is the check that makes the gate load-bearing rather than
        decorative: a new enforcement sentence cannot reach the published
        quick-start without someone naming the control that stands behind it.
        """
        quotes = {binding.quote for binding in BINDINGS}
        unmatched = {sentence: section for sentence, section in _claim_sentences().items() if sentence not in quotes}
        assert not unmatched, (
            "These quick-start sentences make an enforcement claim and have no ClaimBinding:\n"
            + "\n".join(f"  [{section}] {sentence}" for sentence, section in unmatched.items())
            + "\n\nAdd a ClaimBinding whose quote is the WHOLE sentence, naming the control that "
            "proves it. If no control does, set unproven_reason and name the ticket. If the "
            "sentence genuinely makes no capability claim, add it to _EXCLUDED_SENTENCES with a "
            "reason — do not delete the claim from this gate to make it pass."
        )

    @pytest.mark.parametrize("binding", BINDINGS, ids=lambda b: b.claim_id)
    def test_each_binding_matches_exactly_one_whole_sentence(self, binding: ClaimBinding) -> None:
        """Rewording any part of a bound claim fails here.

        Whole-sentence equality, not containment. Containment allowed a sentence
        to carry extra unbound claims — up to and including its own negation —
        while one bound fragment kept the gate green.
        """
        matches = [sentence for sentence in _scanned_sentences() if sentence == binding.quote]
        assert len(matches) == 1, (
            f"ClaimBinding {binding.claim_id!r} must match exactly one whole sentence in "
            f"{_QUICK_START.name}; it matched {len(matches)}.\nIts quote is:\n  {binding.quote!r}\n"
            "The claim was reworded, split, or merged. Update the quote to the new whole "
            "sentence and re-check that the named controls still prove it."
        )

    def test_no_two_bindings_claim_the_same_sentence(self) -> None:
        quotes = [binding.quote for binding in BINDINGS]
        duplicates = {quote for quote in quotes if quotes.count(quote) > 1}
        assert not duplicates, (
            f"More than one ClaimBinding quotes the same sentence: {duplicates}. "
            "Split responsibility like that and neither binding owns the claim."
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
    def test_a_claim_is_either_proven_or_openly_unproven(self, binding: ClaimBinding) -> None:
        """Every claim, with no exempt category.

        There used to be a ``kind`` field here, and setting it to "lifecycle"
        skipped this check entirely — a one-word bypass that needed no ticket
        and no control. It was removed rather than fixed.
        """
        assert binding.controls or binding.unproven_reason, (
            f"Claim {binding.claim_id!r} names no control and gives no unproven_reason. One or "
            "the other is required: a documented claim with neither is exactly the unbacked "
            "assertion AAASM-5526 exists to eliminate."
        )
        if not binding.controls:
            assert re.search(r"AAASM-\d+", binding.unproven_reason), (
                f"Claim {binding.claim_id!r} is unproven but its reason names no ticket. An "
                "unproven claim must be traceable to the work that resolves it. Reason given: "
                f"{binding.unproven_reason!r}"
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
