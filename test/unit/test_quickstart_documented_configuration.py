"""What the documented quick-start configuration actually does (AAASM-5661).

Epic AAASM-5526.

Why the AAASM-5529 controls cannot see this
-------------------------------------------

``test_quickstart_negative_control.py`` proves that a runtime ``deny`` prevents
the effect a tool exists to produce. Each of its controls calls
``install_fake_core()`` first, which supplies an authoritative native runtime.
The configuration ``docs/quick-start.md`` §3 hands a reader has no such runtime:
a pure-Python ``pip install agent-assembly`` carries no ``agent_assembly._core``
extension, and the quick-start's own example runs offline with nothing listening
on the gateway URL it passes. A control that installs the authority first is
therefore structurally unable to observe what happens when there is none — it is
not a weaker version of this control, it is a control over a different program.

What this module runs
---------------------

The four keyword arguments the quick-start passes, and nothing else. In
particular ``enforcement_mode`` is left unset, because the page never mentions
it: the posture under test has to be the one a reader gets by following the page,
not one this file selects.

The governed call is driven through **Agno's own** ``FunctionCall.execute`` —
the chokepoint ``AgnoPatch`` patches and the entry point the page's Agno tab
uses — rather than through the SDK's internal ``run_governed_async_tool``. Going
through the framework is what makes "an interceptor is installed" an observable
fact rather than an assumption: if the SDK installed nothing, or installed
something that waves calls through, Agno runs the body and the file appears.

What it establishes, in ADR 0033 §6 terms
-----------------------------------------

In this configuration the SDK **Evaluates** no policy — there is no authority to
produce a decision — and each governed tool call is **Denied before execution**
by the fail-closed posture (AAASM-4760), carrying a reason that names the missing
extension rather than a policy rule. Both halves are asserted, because the first
without the second would let a future silent pass-through look identical to a
policy allow.

The ``FALSIFICATION`` case runs the same Agno tool with no ``init_assembly`` at
all. It must write the file; if it stops doing so, the absence asserted above has
some other cause and every assertion here is vacuous.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from agno.tools.function import Function, FunctionCall

from agent_assembly import init_assembly
from agent_assembly.core import assembly as core_assembly
from agent_assembly.core.runtime_interceptor import _native_core_available

from .negative_control import FileSideEffect

#: The three connection arguments docs/quick-start.md §3 passes, verbatim in
#: shape: an http:// loopback gateway URL, a literal key, a per-framework agent
#: id. The values are the page's own; only the agent id is renamed so a parallel
#: run cannot collide with a real one.
_GATEWAY_URL = "http://localhost:7391"
_API_KEY = "demo-key"
_AGENT_ID = "quickstart-documented-config-agent"

#: The prefix Agno's failure result carries when the governance hook refused the
#: call — the framework-visible evidence that the refusal happened before the
#: body, not inside it.
_BLOCKED_PREFIX = "[BLOCKED by governance policy]"

#: A fragment of ``_NATIVE_MISSING_REASON``. Asserting on it distinguishes "the
#: SDK refused because it had no authority to ask" from "a policy rule denied
#: this tool" — two outcomes a reader of the page cannot tell apart from the
#: exception alone, and which the page previously described only as the latter.
_NO_AUTHORITY_FRAGMENT = "the native agent_assembly._core extension is not installed"


@pytest.fixture(autouse=True)
def _cleanup_active_context() -> None:
    """Release the process-singleton context so each control inits cleanly."""
    active = core_assembly._ACTIVE_CONTEXT
    if active is not None and not active.is_shutdown:
        active.shutdown()
    core_assembly._ACTIVE_CONTEXT = None


@pytest.fixture
def file_effect(tmp_path: Path) -> FileSideEffect:
    return FileSideEffect(path=tmp_path / "agno-tool-write.txt")


@pytest.fixture
def documented_context() -> Iterator[Any]:
    """``init_assembly`` with exactly the quick-start's arguments.

    Torn down through the real ``shutdown()`` so the Agno patch this installs
    globally is unwound before the next test runs.
    """
    context = init_assembly(
        gateway_url=_GATEWAY_URL,
        api_key=_API_KEY,
        agent_id=_AGENT_ID,
        mode="sdk-only",
    )
    try:
        yield context
    finally:
        context.shutdown()


def _agno_tool_call(effect: FileSideEffect) -> Any:
    """Build a real Agno ``FunctionCall`` whose body writes ``effect``."""

    def write_to_disk(path: str) -> str:
        return FileSideEffect(path=Path(path)).write("the tool body ran")

    return FunctionCall(
        function=Function.from_callable(write_to_disk),
        arguments={"path": str(effect.path)},
    )


class TestTheConfigurationTheQuickStartHandsAReader:
    def test_the_environment_under_test_has_no_native_authority(self) -> None:
        """Pin the premise, so the controls below cannot quietly change subject.

        Every assertion in this class is about the pure-Python install a reader
        gets from ``pip install agent-assembly``. With the native extension
        present the SDK takes a different branch entirely, and these controls
        would still pass while measuring something else.
        """
        assert _native_core_available() is False, (
            "this suite measures the pure-Python install the quick-start's reader gets; "
            "agent_assembly._core is importable here, so the branch under test is not the "
            "one being exercised"
        )

    def test_a_governance_hook_is_installed_on_agnos_own_tool_path(
        self, documented_context: Any, file_effect: FileSideEffect
    ) -> None:
        """The load-bearing control for AAASM-5661.

        Absence of the file is the assertion; the failure result is corroboration.
        Ordered that way on purpose — an assertion on the result placed first
        would abort before the side effect is examined, so a regression that let
        the body run *and* returned a failure would slip through.
        """
        result = _agno_tool_call(file_effect).execute()

        assert file_effect.occurred() is False
        assert file_effect.content() is None
        assert result.status == "failure"
        assert _BLOCKED_PREFIX in str(result.error)

    def test_the_refusal_is_the_fail_closed_posture_rather_than_a_policy_decision(
        self, documented_context: Any, file_effect: FileSideEffect
    ) -> None:
        """The refusal names a missing authority, not a rule that matched.

        This is the half the quick-start got wrong: it described the outcome as a
        policy gate answering, when what answers is a posture taken in the
        absence of anything to ask.
        """
        result = _agno_tool_call(file_effect).execute()

        assert file_effect.occurred() is False
        assert _NO_AUTHORITY_FRAGMENT in str(result.error)

    def test_the_agent_is_not_registered_in_this_configuration(self, documented_context: Any) -> None:
        """``registered`` is the programmatic counterpart of the stderr warning."""
        assert documented_context.registered is False

    def test_no_network_sidecar_starts_in_sdk_only_mode(self, documented_context: Any) -> None:
        """What `mode="sdk-only"` actually buys the example: determinism, not enforcement.

        The AAASM-5529 controls monkeypatch ``_start_network_layer`` away, so they
        cannot speak to this; here the real one runs. Asserting the shutdown hook
        is the no-op — not merely that ``network_mode`` reads ``"sdk-only"`` —
        because the mode string is what the caller asked for, and a started
        sidecar would leave a real teardown behind.
        """
        assert documented_context.network_mode == "sdk-only"
        assert documented_context._network_shutdown is core_assembly._noop_shutdown

    def test_startup_reports_both_the_registration_and_the_enforcement_gap(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The quick-start now tells a reader init warns about two things. This is both.

        They travel on different channels — registration on ``sys.stderr`` so a
        ``logging`` filter cannot drop it, the enforcement gap through
        ``warnings`` — so asserting one and assuming the other would leave the
        documented sentence half-covered.
        """
        with pytest.warns(UserWarning, match="native runtime extension"):
            context = init_assembly(
                gateway_url=_GATEWAY_URL,
                api_key=_API_KEY,
                agent_id=_AGENT_ID,
                mode="sdk-only",
            )
        context.shutdown()

        assert "the agent is NOT registered" in capsys.readouterr().err

    def test_falsification_the_same_agno_tool_ungoverned_writes_the_file(self, file_effect: FileSideEffect) -> None:
        """No ``init_assembly``, no hook. If this stops writing, the class above is vacuous."""
        result = _agno_tool_call(file_effect).execute()

        assert file_effect.occurred() is True
        assert file_effect.content() == "the tool body ran"
        assert result.status == "success"


class TestTheWorkaroundTheFrameworkTabsCarry:
    """The tabs' revert-and-re-apply step, which the page now explains rather than hides.

    Three tabs carried a comment saying ``init_assembly()`` installs a *no-op*
    hook offline. That description predates AAASM-4760 — the hook installed there
    is deny-all, not a no-op — and a workaround written down three times is the
    strongest available evidence that the gap was known in practice. The tab
    bodies are generated from ``quickstart_snippets/`` (vendored from the
    ``examples`` repo), so their comments are not this repo's to rewrite; the
    prose section this ticket added is. This control pins the step the prose now
    describes, so an upstream snippet change that drops it turns the sentence red
    instead of leaving it quietly false.
    """

    def test_the_tabs_still_revert_the_hook_init_assembly_installed(self) -> None:
        quick_start = Path(__file__).resolve().parents[2] / "docs" / "quick-start.md"
        generated = quick_start.read_text(encoding="utf-8").split("BEGIN GENERATED: quickstart-framework-tabs")[1]
        generated = generated.split("END GENERATED: quickstart-framework-tabs")[0]

        # "several" in the prose, pinned to a floor rather than an exact count —
        # a fourth tab adopting the same workaround should not fail a sentence
        # that stays true, and a drop to one should not pass under a word that
        # says more than one.
        assert generated.count(".revert()") >= 2, (
            "the quick-start's generated tabs no longer revert the hook init_assembly() "
            "installed; the 'What this offline example evaluates' section says they do"
        )
