"""Drift gate binding the quick-start's claims to the controls that prove them.

AAASM-5529, Epic AAASM-5526.

Every sentence in ``docs/quick-start.md`` must be either **bound** to a control
that proves it, or **explicitly allow-listed** as making no capability claim.
There is no third state and no keyword filter.

Why the default is inverted
---------------------------

Earlier revisions only scanned sentences matching an enforcement vocabulary.
Review appended three plain sentences that used none of the 21 terms — the last
of them, *"Tool bodies always execute; the policy result is recorded alongside
them"*, is the negation of the product — and all three gates stayed green.
Widening 3 → 21 terms closed the instance and not the class: **a keyword
allow-list cannot be completed, because whoever adds the claim picks the words
after reading the list.**

So the vocabulary no longer gates anything. It survives only as a *severity
hint* in the failure message, and as the trigger for a stricter allow-list rule
(:data:`_ALLOWED` entries whose sentence matches it need a bespoke written
justification, not a category).

There are no section-level exclusions either. An excluded section was a black
hole: the guard checked the heading still existed and said nothing about its
contents, so a claim inserted into ``## Next steps`` was never scanned at all.

What this gate proves
---------------------

#. **Every sentence in the document is accounted for.** Add a sentence anywhere
   — any section, any wording — and it fails until someone binds it or
   allow-lists it by exact text.
#. **A binding matches a whole sentence, exactly** (``==``, never ``in``), and
   exactly one binding may match a sentence. Substring containment let a
   sentence carry extra unbound claims, including its own negation.
#. **Every control a binding names still exists**, extracted from the control
   modules' ASTs rather than transcribed.
#. **Every claim is proven or openly unproven**, with no exempt category, and an
   unproven claim must name a ticket that is *not* the ticket this module
   implements — a pointer at one's own ticket resolves to a closed issue the
   moment that ticket merges.
#. **Comments are stripped before scanning**, because a reader cannot see them.
   Leaving them in let a bound claim be commented out of the rendered page while
   the gate still counted it.

What this gate does **not** prove
---------------------------------

It does not execute, import or type-check a quick-start snippet.
``quickstart_snippets/`` is a vendored verbatim copy of regions from the
``examples`` repository (``ruff.toml`` excludes it), and the snippets reference
names they never define. The ``quickstart-tabs-check`` drift job round-trips
them as *text* only. Neither job runs a snippet.

Nor does binding a claim make it true. A binding records which control stands
behind a sentence; where none does, it says so and names the ticket.
"""

from __future__ import annotations

import ast
import importlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# NOTE: SDK symbols a claim names are resolved lazily, by module path and
# attribute name, rather than imported here. Importing them at module scope
# makes a rename a *collection* error, aborting before the assertion meant to
# catch it can run.

#: The ticket this module implements. An unproven claim may not name it — see
#: test_an_unproven_reason_does_not_name_the_implementing_ticket.
IMPLEMENTING_TICKET = "AAASM-5529"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_QUICK_START = _REPO_ROOT / "docs" / "quick-start.md"

#: Modules a binding may name a control from.
_CONTROL_MODULES = (
    Path(__file__).with_name("test_quickstart_negative_control.py"),
    Path(__file__).with_name("test_assembly.py"),
)

#: NOT a gate. A severity hint in the failure message, and the trigger for the
#: stricter allow-list rule below. See the module docstring for why gating on a
#: keyword list is unsound.
_ENFORCEMENT_VOCABULARY = re.compile(
    r"(?i)\bdenie[sd]\b|\bdeny\b|\bblocked\b|\bblocking\b|\bnever runs?\b"
    r"|\bbefore execution\b|\bchecked against\b|\benforces?\b|\benforced\b"
    r"|\bpassthrough\b|\bdiscards?\b|\bdiscarded\b|\bthrows?\b|\brejects?\b"
    r"|\brouted\b|\bintercepts?\b|\binterception\b|\bgovern(s|ed|ance)?\b"
    r"|\bverified\b|\bprotection\b|\bunprotected\b|\bbypass(ed|es)?\b"
)

#: Allow-list categories. A category is only permitted for a sentence that does
#: NOT match the vocabulary above; anything that does needs a written reason.
_NOT_A_CAPABILITY_CLAIM = "Descriptive or instructional prose. Says nothing about what governance does to a tool call."
_NAVIGATION = "A cross-reference. The claim, if any, lives on the page linked to and is gated there."


@dataclass(frozen=True)
class ClaimBinding:
    """One documented claim and the controls that stand behind it."""

    claim_id: str
    #: The claim as a WHOLE sentence, flattened. Compared with ==, not `in`.
    quote: str
    #: ``ClassName::test_name`` or ``test_name`` ids from _CONTROL_MODULES.
    controls: tuple[str, ...] = ()
    #: Set when no control proves the claim. Must name a ticket, and must not
    #: name IMPLEMENTING_TICKET.
    unproven_reason: str = ""
    #: Backticked SDK identifiers the claim names -> the module they live in.
    symbols: dict[str, str] = field(default_factory=dict)


_DENY_CONTROLS = (
    "TestFilesystemSideEffect::test_negative_control_denied_write_leaves_no_file",
    "TestNetworkSideEffect::test_negative_control_denied_egress_never_reaches_the_listener",
)
_ALLOW_AND_DENY_CONTROLS = (
    "TestFilesystemSideEffect::test_positive_control_allowed_write_creates_the_file",
    *_DENY_CONTROLS,
    "TestNetworkSideEffect::test_positive_control_allowed_egress_reaches_the_listener",
)

#: AAASM-5661 measured the documented configuration: it reaches no gateway and
#: installs a deny-all fail-closed interceptor. Every control here calls
#: install_fake_core(), supplying an authoritative runtime the documented path
#: does not have, so none of them exercises what these sentences describe.
#: Binding one would launder that gap into evidence.
_DOCUMENTED_PATH_UNMEASURED = (
    "AAASM-5661: the documented configuration was measured and does not behave as this "
    "sentence says. No control covers it — every control in "
    "test_quickstart_negative_control.py installs a fake native core the documented "
    "path does not have."
)

BINDINGS: tuple[ClaimBinding, ...] = (
    ClaimBinding(
        claim_id="tool-calls-pass-through-the-policy-gate",
        quote=(
            "By the end you'll have an agent — in whichever framework you already use — whose "
            "tool calls pass through the Agent Assembly policy gate, and it runs **offline** "
            "against a local policy, so you need no API keys and no network access to the "
            "outside world."
        ),
        # Found by inverting the default. It states the page's central promise
        # and matches no enforcement keyword, so every earlier revision of this
        # gate was blind to it.
        unproven_reason=_DOCUMENTED_PATH_UNMEASURED,
    ),
    ClaimBinding(
        claim_id="governs-whichever-framework-you-use",
        quote="Agent Assembly governs whichever agent framework you already use.",
        # A breadth claim with no boundary. The controls prove the shared
        # governed-tool chain, not "whichever framework"; per ADR 0033 §6 a
        # claim like this needs a named boundary or a qualification.
        unproven_reason=(
            "AAASM-5536: an unbounded breadth claim. The controls prove the shared "
            "governed-tool chain behind two adapter tabs, not every framework the page "
            "offers, and no control enumerates them. AAASM-5536 is the documentation "
            "claim gate that forces such a sentence to name its boundary or be qualified."
        ),
    ),
    ClaimBinding(
        claim_id="auto-start-probes-and-starts-a-gateway",
        quote=(
            "**Let the SDK auto-start one.** Call `init_assembly()` with no `gateway_url`; the "
            "SDK probes `http://localhost:7391` and, if nothing answers, runs `aasm start "
            "--mode local --foreground` for you."
        ),
        # Measured during this ticket's scoping pass and reported: the
        # [project.scripts] aasm console script shadows the bundled Rust binary
        # on PATH, so find_aasm_binary() resolves the Python one, which has no
        # `start` subcommand. The documented auto-start therefore cannot work
        # from a clean install.
        unproven_reason=(
            "AAASM-5661: no control covers the documented auto-start path, and it was "
            "measured not to work from a clean install — the [project.scripts] aasm "
            "console script shadows the bundled binary, and the shadowing one has no "
            "'start' subcommand."
        ),
    ),
    ClaimBinding(
        claim_id="no-arg-init-connects-and-appears-in-dashboard",
        quote=(
            "You don't configure `:50051` yourself — registration dials it automatically — so a "
            "no-argument `init_assembly()` both connects and shows the agent in the dashboard."
        ),
        unproven_reason=_DOCUMENTED_PATH_UNMEASURED,
    ),
    ClaimBinding(
        claim_id="gateway-returns-allow-deny-decisions",
        quote=("`init_assembly()` needs to reach a **gateway** — the policy brain that returns allow/deny decisions."),
        unproven_reason=_DOCUMENTED_PATH_UNMEASURED,
    ),
    ClaimBinding(
        claim_id="init-routes-every-tool-call",
        quote=(
            "**`init_assembly()` wired in governance.** It registered the agent with the gateway "
            "and auto-loaded the adapter for your framework — every tool call from this point on "
            "is routed through the policy gate."
        ),
        unproven_reason=_DOCUMENTED_PATH_UNMEASURED,
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
        # Both halves. The negative controls prove the "before" by absence of
        # the side effect; the positive controls prove the probe would have seen
        # that effect had it happened. Either alone is vacuous.
        controls=_ALLOW_AND_DENY_CONTROLS,
    ),
    ClaimBinding(
        claim_id="with-block-tears-everything-down",
        quote=(
            "**The `with` block tore everything down on exit** — adapter hooks were unwound and "
            "the gateway connection closed, leaving the process exactly as it was before."
        ),
        # Previously exempt under the removed `kind` field. Under the inverted
        # default it is a claim like any other and needs a control.
        controls=("test_context_manager_shutdown_calls_adapter_unregister_hooks",),
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
        # This previously named AAASM-5529 — the ticket this module implements —
        # which would have resolved to a closed issue the moment this merged.
        # No ticket currently owns *proving* it: nothing in this SDK starts or
        # probes a proxy or eBPF layer, so the honest resolution is
        # qualification rather than proof, which is AAASM-5536's job.
        unproven_reason=(
            "AAASM-5536: no control in the Python SDK starts or probes a proxy or eBPF "
            "layer, so nothing here distinguishes 'the mode adds interception' from 'the "
            "mode is selected'. No ticket owns proving this; the expected resolution is "
            "that AAASM-5536's claim gate forces the sentence to name its boundary."
        ),
    ),
)

#: Every sentence in the quick-start that makes no capability claim, keyed
#: exactly. A category is only permitted where the sentence does not match
#: _ENFORCEMENT_VOCABULARY; anything that does needs a written justification.
_ALLOWED: dict[str, str] = {
    "Govern your first agent in about five minutes.": (
        "The page's title line. It matches the vocabulary on the imperative verb "
        "'Govern', which names what the reader is about to do, not what the product "
        "guarantees. The substantive promise is the next sentence, which IS bound."
    ),
    "The package is published on PyPI as [`{{ aa.python_sdk.package_name }}`]({{ aa.urls.pypi }}) (current version: `{{ aa.python_sdk.version }}`).": _NOT_A_CAPABILITY_CLAIM,
    '=== "pip"': _NOT_A_CAPABILITY_CLAIM,
    '=== "uv"': _NOT_A_CAPABILITY_CLAIM,
    '=== "poetry"': _NOT_A_CAPABILITY_CLAIM,
    '=== "conda"': _NOT_A_CAPABILITY_CLAIM,
    "`{{ aa.python_sdk.package_name }}` is not published on conda-forge or the Anaconda default channel — create a conda environment, then install from PyPI with `pip` inside it:": _NOT_A_CAPABILITY_CLAIM,
    '!!! note "`--pre` is required for now" Agent Assembly is currently published only as a pre-release on PyPI, and `pip` skips pre-releases unless you pass `--pre` (already included above).': _NOT_A_CAPABILITY_CLAIM,
    "Drop the flag once a stable (non-pre-release) version is published.": _NOT_A_CAPABILITY_CLAIM,
    "`{{ aa.python_sdk.package_name }}` is the pure-Python client.": _NOT_A_CAPABILITY_CLAIM,
    "`{{ aa.python_sdk.package_name }}[runtime]` additionally pulls a platform wheel (`manylinux`, `macosx`) that bundles the `{{ aa.python_sdk.cli_name }}` gateway/runtime binary, so a local gateway is available without a separate install.": _NOT_A_CAPABILITY_CLAIM,
    "You have three options:": _NOT_A_CAPABILITY_CLAIM,
    "This needs the `aasm` binary on your `PATH` (the `agent-assembly[runtime]` extra provides it).": _NOT_A_CAPABILITY_CLAIM,
    "**Run one yourself** with `aasm start --mode local --foreground` in a separate terminal.": _NOT_A_CAPABILITY_CLAIM,
    "For a full gateway walkthrough, see the core [Run the gateway](https://docs.agent-assembly.com/core/latest/quick-start/first-run.html) guide.": _NAVIGATION,
    "**Pass an explicit URL**, as the example below does.": _NOT_A_CAPABILITY_CLAIM,
    "See [Configuration](configuration.md) for the full URL/key resolution chain (`7391` is the local default port).": _NAVIGATION,
    '!!! note "Local-mode transports: `:7391` REST + `:50051` gRPC" Starting local mode binds **two** loopback surfaces in one process:': _NOT_A_CAPABILITY_CLAIM,
    "This runs the REST/dashboard API on `http://localhost:7391` (what `gateway_url` points to, and what the SDK probes and auto-starts) **and** the gRPC `AgentLifecycleService` on `127.0.0.1:50051`, which is the endpoint the native SDK uses to **register** your agent.": _NOT_A_CAPABILITY_CLAIM,
    "`:8080` is **not** the local gateway port; ignore older docs or examples that point registration there.": _NOT_A_CAPABILITY_CLAIM,
    "To confirm both surfaces are actually up rather than guessing from the SDK's behavior, check them directly:": _NOT_A_CAPABILITY_CLAIM,
    "Pick your framework below — each tab is the **governance-wiring slice** (`init_assembly()` plus "
    "that framework's adapter hookup) taken verbatim from that framework's runnable example in the "
    "[examples repo](https://github.com/ai-agent-assembly/examples/tree/master/python).": (
        "Describes where the tab content comes from. 'governance-wiring slice' names the "
        "excerpt's provenance, not an enforcement outcome; it asserts nothing about "
        "whether a denied call is stopped."
    ),
    "Copy the full, runnable script — imports, tools, and the agent run — from the linked example; "
    "the slice below is the part that wires in governance.": (
        "An instruction to the reader about which lines to copy. 'wires in governance' "
        "identifies the excerpt, and makes no claim about what that wiring then does to "
        "a tool call."
    ),
    'Every example runs **offline** in `mode="sdk-only"` against a local policy, so you can try it with no API keys and no outbound network.': _NOT_A_CAPABILITY_CLAIM,
    '=== "Agno"': _NOT_A_CAPABILITY_CLAIM,
    '!!! note "Version compatibility" Agno was previously published as **Phidata**; the rename replaced every `phi.*` import with `agno.*`.': _NOT_A_CAPABILITY_CLAIM,
    "Before (Phidata): `from phi.agent import Agent`": _NOT_A_CAPABILITY_CLAIM,
    "After (Agno): `from agno.agent import Agent`": _NOT_A_CAPABILITY_CLAIM,
    "Source: [Agno's official Phidata → Agno migration guide](https://docs.agno.com/how-to/phidata-to-agno).": _NAVIGATION,
    '=== "AutoGen"': _NOT_A_CAPABILITY_CLAIM,
    "!!! note \"Version compatibility\" AutoGen's `v0.4` rewrite (2024) replaced the single `pyautogen` package's `autogen.agentchat` namespace with separate `autogen-agentchat` / `autogen-core` / `autogen-ext` packages, and `llm_config` with an explicit `model_client`.": _NOT_A_CAPABILITY_CLAIM,
    "Before (v0.2, `pyautogen`): `from autogen.agentchat import AssistantAgent`": _NOT_A_CAPABILITY_CLAIM,
    "After (v0.4+): `from autogen_agentchat.agents import AssistantAgent`": _NOT_A_CAPABILITY_CLAIM,
    "Source: [AutoGen's official v0.2 → v0.4 migration guide](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/migration-guide.html).": _NAVIGATION,
    '=== "CrewAI"': _NOT_A_CAPABILITY_CLAIM,
    '=== "Custom (no framework)"': _NOT_A_CAPABILITY_CLAIM,
    '=== "Google ADK"': _NOT_A_CAPABILITY_CLAIM,
    '=== "Haystack"': _NOT_A_CAPABILITY_CLAIM,
    '!!! note "Version compatibility" Haystack 2.0 replaced the `farm-haystack` package with `haystack-ai` and flattened node imports into `haystack.components.*`; the two package versions cannot coexist in one environment.': _NOT_A_CAPABILITY_CLAIM,
    "Before (Haystack 1.x, `farm-haystack`): `from haystack.nodes import BM25Retriever`": _NOT_A_CAPABILITY_CLAIM,
    "After (Haystack 2.x, `haystack-ai`): `from haystack.components.retrievers.in_memory import InMemoryBM25Retriever`": _NOT_A_CAPABILITY_CLAIM,
    "Source: [Haystack's official migration guide](https://docs.haystack.deepset.ai/docs/migration).": _NAVIGATION,
    '=== "LangChain"': _NOT_A_CAPABILITY_CLAIM,
    '!!! note "Version compatibility" LangChain\'s import surface moved twice: `langchain-core` split out of `langchain` across the `0.1` → `0.3` series (2024), and the `1.0` rewrite (2025) moved legacy chains/agents/tools out of `langchain` entirely into `langchain-classic`.': _NOT_A_CAPABILITY_CLAIM,
    "Before (`<1.0`): `from langchain.agents import AgentExecutor, create_react_agent`": _NOT_A_CAPABILITY_CLAIM,
    "After (`>=1.0`): `from langchain_classic.agents import AgentExecutor, create_react_agent` (requires the separate `langchain-classic` package)": _NOT_A_CAPABILITY_CLAIM,
    "This SDK's own quick-start sample hit exactly this break — see AAASM-4451.": _NOT_A_CAPABILITY_CLAIM,
    "Sources: [LangChain's official v1 migration guide](https://docs.langchain.com/oss/python/migrate/langchain-v1) and the [LangChain v0.3 announcement](https://www.langchain.com/blog/announcing-langchain-v0-3).": _NAVIGATION,
    '=== "LangChain (Research Agent)"': _NOT_A_CAPABILITY_CLAIM,
    '=== "LangGraph"': _NOT_A_CAPABILITY_CLAIM,
    '!!! note "Version compatibility" LangGraph `1.0` deprecated `langgraph.prebuilt.create_react_agent` in favor of LangChain\'s own agent constructor.': _NOT_A_CAPABILITY_CLAIM,
    "Before (`<1.0`): `from langgraph.prebuilt import create_react_agent`": _NOT_A_CAPABILITY_CLAIM,
    "After (`>=1.0`): `from langchain.agents import create_agent`": _NOT_A_CAPABILITY_CLAIM,
    "Source: [LangGraph's official v1 migration guide](https://docs.langchain.com/oss/python/migrate/langgraph-v1).": _NAVIGATION,
    '=== "LlamaIndex"': _NOT_A_CAPABILITY_CLAIM,
    '!!! note "Version compatibility" LlamaIndex `v0.10.0` (February 2024) split the monolithic `llama_index` package into a slim `llama-index-core` plus versioned per-provider packages (`llama-index-llms-openai`, etc.).': _NOT_A_CAPABILITY_CLAIM,
    "An automated `llamaindex-cli upgrade` tool is provided for the migration.": _NOT_A_CAPABILITY_CLAIM,
    "Before (`<0.10`): `from llama_index.llms import OpenAI`": _NOT_A_CAPABILITY_CLAIM,
    "After (`>=0.10`): `from llama_index.llms.openai import OpenAI` (from the separate `llama-index-llms-openai` package)": _NOT_A_CAPABILITY_CLAIM,
    "Source: [LlamaIndex's official v0.10 migration guide](https://www.llamaindex.ai/blog/llamaindex-v0-10-838e735948f8).": _NAVIGATION,
    '=== "Microsoft Agent Framework"': _NOT_A_CAPABILITY_CLAIM,
    '=== "OpenAI Agents SDK"': _NOT_A_CAPABILITY_CLAIM,
    '=== "Pydantic AI"': _NOT_A_CAPABILITY_CLAIM,
    '=== "Semantic Kernel"': _NOT_A_CAPABILITY_CLAIM,
    '=== "smolagents"': _NOT_A_CAPABILITY_CLAIM,
    '!!! note "Version compatibility" smolagents `v1.14.0` (April 2025) renamed `HfApiModel` to `InferenceClientModel` to reflect that it wraps any Hugging Face Inference Provider, not just the HF Hub; backward-compatible re-export was restored in `v1.24.0`.': _NOT_A_CAPABILITY_CLAIM,
    "Before (`<1.14`): `from smolagents import HfApiModel`": _NOT_A_CAPABILITY_CLAIM,
    "After (`>=1.14`): `from smolagents import InferenceClientModel`": _NOT_A_CAPABILITY_CLAIM,
    "Source: [smolagents releases](https://github.com/huggingface/smolagents/releases).": _NAVIGATION,
    '=== "Strands Agents"': _NOT_A_CAPABILITY_CLAIM,
    "That's the product working.": _NOT_A_CAPABILITY_CLAIM,
    "It's the most portable mode and the best choice for deterministic, offline examples and tests.": _NOT_A_CAPABILITY_CLAIM,
    "**[Core Concepts](concepts/index.md)** — the adapter pattern, the `init_assembly()` lifecycle, and the modes/enforcement model.": _NAVIGATION,
    "**[Examples](examples/index.md)** — wire the SDK into the framework you actually use.": _NAVIGATION,
    "**[Configuration](configuration.md)** — drop the hard-coded URL and key; let the resolver chain find them.": _NAVIGATION,
    "See [Handling allow/deny decisions](guides/handling-decisions.md) for how to catch and respond "
    "to those, and [Troubleshooting](troubleshooting.md) if `init_assembly()` itself raised.": (
        "Navigational cross-reference. It matches the vocabulary only through the linked "
        "page's title ('allow/deny decisions'); it asserts nothing about what governance "
        "does. The claim it points at is gated on that page."
    ),
}


_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_FENCE = re.compile(r"```.*?```", re.DOTALL)
#: Comments are invisible to a reader, so a bound claim commented out of the
#: rendered page must not still satisfy this gate. Stripped for the same reason
#: fences are. Go's CommonMark HTML blocks and MDX's {/* */} form are covered
#: too, so the three gates strip the same things.
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_MDX_COMMENT = re.compile(r"\{/\*.*?\*/\}", re.DOTALL)
_LIST_MARKER = re.compile(r"(?m)^\s*(?:[-*+]|\d+\.)\s+")
_UNIT_SPLIT = re.compile(r"(?m)^(?=\s*(?:[-*+]|\d+\.)\s|\|)")
#: '.' and '?' only. '!' is not a terminator here because mkdocs admonitions
#: open with '!!! note', which would otherwise split into a bare '!!!' unit.
_SENTENCE_END = re.compile(r"(?<=[.?])\s+")


def _document() -> str:
    """Read the quick-start with line endings normalised to LF.

    Without this the paragraph split never fires on a CRLF checkout and the
    whole section collapses into one sentence. Node's Windows CI legs caught
    exactly that; this repo's CI is Linux-only, so it is latent here.
    """
    return _QUICK_START.read_text(encoding="utf-8").replace("\r\n", "\n")


def _scanned_sentences() -> dict[str, str]:
    """Return ``flattened sentence -> section heading`` for the WHOLE document.

    No section is skipped. A section-level exclusion was a black hole: the guard
    checked the heading still existed and said nothing about its contents, so a
    claim inserted into an excluded section was never scanned.
    """
    body = _document()
    body = _FRONT_MATTER.sub("", body)
    for pattern in (_FENCE, _HTML_COMMENT, _MDX_COMMENT):
        body = pattern.sub("\n\n", body)

    sentences: dict[str, str] = {}
    section = "(preamble)"
    for chunk in re.split(r"(?m)^(#{1,6} .*)$", body):
        if chunk is None:
            continue
        if re.match(r"^#{1,6} ", chunk):
            section = chunk.strip()
            continue
        for paragraph in chunk.split("\n\n"):
            for unit in _UNIT_SPLIT.split(paragraph):
                for raw in _SENTENCE_END.split(_LIST_MARKER.sub("", unit)):
                    flat = re.sub(r"\s+", " ", raw).strip()
                    if flat:
                        sentences[flat] = section
    return sentences


def _control_node_ids() -> set[str]:
    """Extract control ids from the control modules' ASTs, not transcribed."""
    node_ids: set[str] = set()
    for module in _CONTROL_MODULES:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) and child.name.startswith("test_"):
                        node_ids.add(f"{node.name}::{child.name}")
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test_"):
                node_ids.add(node.name)
    return node_ids


class TestTheGateCanSeeWhatItGates:
    """Positive controls. An empty parse and a clean result look identical."""

    def test_the_whole_document_is_read_and_split(self) -> None:
        assert len(_scanned_sentences()) > 60, "too few sentences parsed from the whole quick-start"

    def test_the_scan_covers_every_section_including_the_last(self) -> None:
        sections = set(_scanned_sentences().values())
        assert len(sections) >= 6, f"the scan reached only {len(sections)} sections: {sections}"
        assert "## Next steps" in sections, (
            "'## Next steps' is not in the scan. It used to be excluded by name, which made it "
            "a black hole: a claim inserted there was never seen. It must be scanned."
        )

    def test_comments_are_stripped_before_scanning(self) -> None:
        """A commented-out sentence must not satisfy a binding.

        Positive control for the strip: the document contains HTML comments, and
        none of their content may appear in the scan.
        """
        assert "<!--" in _document(), (
            "this control assumes the quick-start still contains an HTML comment; if it no "
            "longer does, re-point it rather than deleting it"
        )
        joined = " ".join(_scanned_sentences())
        assert "BEGIN GENERATED" not in joined, "HTML comment content leaked into the scan"

    def test_the_ast_extraction_finds_controls_in_every_control_module(self) -> None:
        node_ids = _control_node_ids()
        assert "TestFilesystemSideEffect::test_negative_control_denied_write_leaves_no_file" in node_ids
        assert "test_context_manager_shutdown_calls_adapter_unregister_hooks" in node_ids


class TestEverySentenceIsAccountedFor:
    def test_no_sentence_is_unbound_and_unallowed(self) -> None:
        """Every sentence must be bound or allow-listed. There is no third state.

        This is the inversion. A keyword filter cannot be completed, because
        whoever adds a claim picks the words after reading the filter — review
        appended three plain sentences, one of them the negation of the product,
        and every keyword-gated revision of this gate stayed green.
        """
        quotes = {binding.quote for binding in BINDINGS}
        loose = {
            sentence: section
            for sentence, section in _scanned_sentences().items()
            if sentence not in quotes and sentence not in _ALLOWED
        }
        rendered = "\n".join(
            f"  [{'CLAIM-LIKE' if _ENFORCEMENT_VOCABULARY.search(s) else 'prose'}] [{sec}] {s}"
            for s, sec in loose.items()
        )
        assert not loose, (
            f"{len(loose)} sentence(s) in {_QUICK_START.name} are neither bound nor "
            f"allow-listed:\n{rendered}\n\n"
            "CLAIM-LIKE marks sentences matching the enforcement vocabulary — a severity "
            "hint only; a sentence marked 'prose' can still be a claim, which is exactly "
            "why this gate does not filter on the vocabulary.\n\n"
            "For each: add a ClaimBinding whose quote is the WHOLE sentence and which names "
            "the control that proves it (or an unproven_reason naming a ticket), or add it "
            "to _ALLOWED with a category. A sentence matching the vocabulary needs a written "
            "justification in _ALLOWED, not a category."
        )

    def test_nothing_is_both_bound_and_allowed(self) -> None:
        overlap = {binding.quote for binding in BINDINGS} & set(_ALLOWED)
        assert not overlap, f"these sentences are both bound and allow-listed: {overlap}"

    @pytest.mark.parametrize("binding", BINDINGS, ids=lambda b: b.claim_id)
    def test_each_binding_matches_exactly_one_whole_sentence(self, binding: ClaimBinding) -> None:
        matches = [s for s in _scanned_sentences() if s == binding.quote]
        assert len(matches) == 1, (
            f"ClaimBinding {binding.claim_id!r} must match exactly one whole sentence in "
            f"{_QUICK_START.name}; it matched {len(matches)}.\nIts quote is:\n  {binding.quote!r}\n"
            "The claim was reworded, split, merged, or commented out. Update the quote to the "
            "new whole sentence and re-check that the named controls still prove it."
        )

    def test_no_two_bindings_claim_the_same_sentence(self) -> None:
        quotes = [b.quote for b in BINDINGS]
        duplicates = {q for q in quotes if quotes.count(q) > 1}
        assert not duplicates, f"more than one ClaimBinding quotes the same sentence: {duplicates}"


class TestTheAllowListCannotBecomeABypass:
    def test_every_allowed_sentence_is_still_present_verbatim(self) -> None:
        """A stale entry cannot silently exempt a reworded claim."""
        scanned = _scanned_sentences()
        stale = [s for s in _ALLOWED if s not in scanned]
        assert not stale, (
            "_ALLOWED contains sentences that no longer appear in the quick-start:\n"
            + "\n".join(f"  {s!r}" for s in stale)
            + "\nThey were reworded or removed. Delete the stale entries, and if a replacement "
            "makes a capability claim, bind it."
        )

    def test_a_claim_like_sentence_needs_a_written_justification(self) -> None:
        """Allow-listing something that reads like a claim costs a sentence of prose.

        The category constants are deliberately unusable here: waving through a
        sentence that matches the vocabulary must require saying why.
        """
        categories = {_NOT_A_CAPABILITY_CLAIM, _NAVIGATION}
        offenders = {
            sentence: reason
            for sentence, reason in _ALLOWED.items()
            if _ENFORCEMENT_VOCABULARY.search(sentence) and reason in categories
        }
        assert not offenders, (
            "These allow-listed sentences match the enforcement vocabulary but are waved "
            "through with a bare category:\n"
            + "\n".join(f"  {s!r}" for s in offenders)
            + "\nReplace the category with a written justification saying why the sentence "
            "makes no capability claim, or bind it."
        )

    def test_every_allow_list_reason_is_non_empty(self) -> None:
        empty = [s for s, reason in _ALLOWED.items() if not reason.strip()]
        assert not empty, f"allow-list entries with no reason: {empty}"


class TestEveryBindingNamesSomethingReal:
    @pytest.mark.parametrize("binding", BINDINGS, ids=lambda b: b.claim_id)
    def test_named_controls_exist(self, binding: ClaimBinding) -> None:
        available = _control_node_ids()
        missing = [c for c in binding.controls if c not in available]
        assert not missing, (
            f"ClaimBinding {binding.claim_id!r} names controls that do not exist: {missing}\n"
            "The control was renamed or removed. Re-point the binding, or mark the claim "
            "unproven and name the ticket."
        )

    @pytest.mark.parametrize("binding", BINDINGS, ids=lambda b: b.claim_id)
    def test_a_claim_is_either_proven_or_openly_unproven(self, binding: ClaimBinding) -> None:
        assert binding.controls or binding.unproven_reason, (
            f"Claim {binding.claim_id!r} names no control and gives no unproven_reason. A "
            "documented claim with neither is the unbacked assertion AAASM-5526 exists to "
            "eliminate."
        )
        if not binding.controls:
            assert re.search(r"AAASM-\d+", binding.unproven_reason), (
                f"Claim {binding.claim_id!r} is unproven but names no ticket. Reason given: {binding.unproven_reason!r}"
            )

    @pytest.mark.parametrize("binding", BINDINGS, ids=lambda b: b.claim_id)
    def test_an_unproven_reason_does_not_name_the_implementing_ticket(self, binding: ClaimBinding) -> None:
        """An unproven claim may not point at the ticket that closes it.

        A reason naming this module's own ticket resolves to a *closed* issue the
        moment this work merges, and nothing would notice: the ticket-shaped
        check above is satisfied by any AAASM-nnnn, open or not.
        """
        assert IMPLEMENTING_TICKET not in binding.unproven_reason, (
            f"Claim {binding.claim_id!r} is registered unproven against {IMPLEMENTING_TICKET}, "
            "the ticket this module implements. On merge that pointer resolves to a closed "
            "issue and the claim is silently orphaned. Name the ticket that will actually "
            "resolve it, or file one."
        )

    @pytest.mark.parametrize("binding", BINDINGS, ids=lambda b: b.claim_id)
    def test_named_sdk_symbols_resolve_to_that_name(self, binding: ClaimBinding) -> None:
        for documented_name, module_path in binding.symbols.items():
            module = importlib.import_module(module_path)
            resolved = getattr(module, documented_name, None)
            assert resolved is not None, (
                f"{_QUICK_START.name} names `{documented_name}` but that symbol no longer "
                f"exists in {module_path}. The documented quick-start now points at something "
                "a reader cannot import."
            )
            assert resolved.__name__ == documented_name, (
                f"{_QUICK_START.name} names {documented_name!r} but the resolved symbol "
                f"reports __name__ == {resolved.__name__!r}."
            )
