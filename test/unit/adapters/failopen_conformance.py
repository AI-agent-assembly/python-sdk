"""Adapter-driver registry + fault-injection harness for the fail-open conformance matrix.

This is the systemic answer to the per-round fail-open whack-a-mole (openai_agents
AAASM-4734 → AAASM-4782, langchain AAASM-4790): instead of adding one bespoke
regression test each time a single adapter is caught failing open, every governing
adapter is driven through the *same* fault scenarios under the *same* enforcement
postures, and a completeness check makes a new (or regressed) adapter that ships
without a driver fail the suite.

The harness reuses the technique the per-adapter tests already proved: build a fake
framework tool whose real body flips a ``ran`` flag, invoke the adapter's *real*
governance wrapper (``_apply_*`` / callback helper) against a fake interceptor whose
behaviour is set per scenario, and report whether the underlying tool actually ran.

What is asserted (the security invariant):

* Under an **enforce** posture — explicit ``enforce`` and the ``None``/omitted default,
  which :func:`_local_posture_is_enforce` resolves to enforce — every fault (S1–S5),
  plus the deny controls (S6–S7), MUST block the tool: it does not run. Only the
  explicit allow control (S8) runs.
* Under a **fail-open** posture (``observe`` / ``disabled``) the faults (S1–S5) proceed
  by design (the tool runs), preserving the dry-run / hermetic behaviour, while an
  authoritative deny (S6–S7) still blocks in every posture.

The scenarios inject the *raw* fault at the interceptor boundary (no verdict, an
error sentinel, garbage, a missing method, a pending-approval fault, a deny whose
audit sink raises) so the ADAPTER's own normalize + fail-closed logic is what is
under test — not a pre-decided verdict handed to it.
"""

from __future__ import annotations

import contextlib
import importlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from agent_assembly.core.runtime_interceptor import _local_posture_is_enforce
from agent_assembly.exceptions import GatewayError

# --- Scenarios -------------------------------------------------------------

# The interceptor faults the adapter's pre-execution check can hit. Each value is
# the raw fault injected at the ``check_tool_start`` boundary (or its absence); the
# adapter's own ``_normalize_decision`` / ``_missing_interceptor_decision`` is what
# converts it into allow/deny under the active posture.
GATEWAY_UNREACHABLE = "s1_gateway_unreachable"  # check returns None (no verdict)
GOVERNANCE_ERROR = "s2_governance_error"  # check returns an error-sentinel status
MALFORMED_DECISION = "s3_malformed_decision"  # check returns an unrecognized object
MISSING_CHECK_METHOD = "s4_missing_check_method"  # interceptor exposes no check_tool_start
PENDING_FAULT = "s5_pending_fault"  # pending verdict, then approval faults
DENY_AUDIT_RAISES = "s6_deny_audit_raises"  # authoritative deny whose audit sink raises
EXPLICIT_DENY = "s7_explicit_deny"  # authoritative deny (control)
EXPLICIT_ALLOW = "s8_explicit_allow"  # authoritative allow (control)

SCENARIOS: tuple[str, ...] = (
    GATEWAY_UNREACHABLE,
    GOVERNANCE_ERROR,
    MALFORMED_DECISION,
    MISSING_CHECK_METHOD,
    PENDING_FAULT,
    DENY_AUDIT_RAISES,
    EXPLICIT_DENY,
    EXPLICIT_ALLOW,
)

# Authoritative-deny scenarios block regardless of posture; the fault scenarios only
# block under an enforce posture (they fail open under observe / disabled).
_AUTHORITATIVE_DENY = frozenset({DENY_AUDIT_RAISES, EXPLICIT_DENY})

# --- Enforcement modes -----------------------------------------------------

# ``None`` is the advertised default and MUST resolve to the enforce posture
# (AAASM-4130) — the resolution is pinned here through the real production helper so
# an omitted ``enforcement_mode`` can never silently drift to fail-open.
MODES: tuple[tuple[str, str | None], ...] = (
    ("enforce", "enforce"),
    ("omitted_none", None),
    ("observe", "observe"),
    ("disabled", "disabled"),
)


def expected_run(scenario: str, *, is_enforce: bool) -> bool:
    """The tool-ran outcome the governance contract requires for this cell.

    Args:
        scenario: One of :data:`SCENARIOS`.
        is_enforce: Whether the active posture is fail-closed (enforce / the ``None``
            default), as resolved by :func:`_local_posture_is_enforce`.

    Returns:
        ``True`` when the underlying tool is expected to execute, ``False`` when
        governance must block it.
    """
    if scenario == EXPLICIT_ALLOW:
        return True
    if scenario in _AUTHORITATIVE_DENY:
        return False
    # Injected faults (S1–S5): fail closed under enforce, fail open otherwise.
    return not is_enforce


# --- Fake interceptor ------------------------------------------------------


class _FaultInterceptor:
    """Fake governance interceptor whose ``check_tool_start`` injects a scenario fault.

    ``_enforce`` mirrors the real interceptor flag every adapter reads
    (``_interceptor_enforces`` / the LangChain handler's ``_enforce``) so the
    adapter's fail-closed-under-enforce path is exercised authentically.
    """

    def __init__(self, scenario: str, *, enforce: bool) -> None:
        self._scenario = scenario
        self._enforce = enforce

    def check_tool_start(self, **_kwargs: Any) -> object:
        scenario = self._scenario
        if scenario == GATEWAY_UNREACHABLE:
            return None
        if scenario == GOVERNANCE_ERROR:
            return {"status": "error", "reason": "governance transport failure"}
        if scenario == MALFORMED_DECISION:
            return object()
        if scenario == PENDING_FAULT:
            return {"status": "pending", "reason": "awaiting approval"}
        if scenario in _AUTHORITATIVE_DENY:
            return {"status": "deny", "reason": "denied by policy"}
        if scenario == EXPLICIT_ALLOW:
            return {"status": "allow"}
        raise AssertionError(f"no check_tool_start behaviour for scenario {scenario!r}")

    def wait_for_tool_approval(self, **_kwargs: Any) -> object:
        # A faulting approval round-trip returns no authoritative verdict; the
        # adapter must fail closed under enforce and open under observe.
        return None

    def record_result(self, **_kwargs: Any) -> None:
        self._maybe_fail_audit()

    def on_tool_end(self, **_kwargs: Any) -> None:
        self._maybe_fail_audit()

    def _maybe_fail_audit(self) -> None:
        # AAASM-4782: a deny whose audit sink raises must not let the error re-enter
        # the run path and downgrade the decided deny into an allow.
        if self._scenario == DENY_AUDIT_RAISES:
            raise GatewayError("deny-audit sink unavailable")


class _MissingCheckInterceptor:
    """Fake interceptor that exposes no ``check_tool_start`` at all (AAASM-4790).

    Every adapter must route the missing-method case through
    ``_missing_interceptor_decision`` — deny under enforce, allow otherwise — rather
    than silently skipping the pre-execution gate.
    """

    def __init__(self, *, enforce: bool) -> None:
        self._enforce = enforce

    def record_result(self, **_kwargs: Any) -> None:
        return None

    def on_tool_end(self, **_kwargs: Any) -> None:
        return None


def make_fake_interceptor(scenario: str, *, enforce: bool) -> object:
    """Build the fake interceptor for a scenario under the given enforce posture."""
    if scenario == MISSING_CHECK_METHOD:
        return _MissingCheckInterceptor(enforce=enforce)
    return _FaultInterceptor(scenario, enforce=enforce)


# --- Adapter drivers -------------------------------------------------------
#
# Each driver builds a fake framework tool whose body flips ``ran[0]`` and invokes the
# adapter's REAL governance wrapper against ``interceptor``. A driver never inspects
# the deny shape (raise vs sentinel return): the only signal is whether the underlying
# body ran, so the harness handles blocked-by-raise uniformly by catching AssemblyError.

Driver = Callable[[object, list[bool]], Awaitable[None]]


def _assert_sync_and_async_agree(adapter: str, *, sync_ran: bool, async_ran: bool) -> bool:
    """Require an adapter's sync and async tool wrappers to reach the same verdict.

    Adapters that gate both a sync and an async chokepoint (agno
    ``execute``/``aexecute``, llamaindex ``call``/``acall``) wrap the *same*
    governance decision on both paths. A divergence means one path fails open (or
    closed) where the other does not — precisely the bug class this matrix guards
    against — so surface it loudly instead of letting a single shared ``ran`` flag
    mask an async-only regression behind a passing sync path.

    Args:
        adapter: Adapter name, for the failure message.
        sync_ran: Whether the sync wrapper let the tool body run.
        async_ran: Whether the async wrapper let the tool body run.

    Returns:
        The agreed-upon tool-ran outcome (both paths concur).
    """
    assert sync_ran == async_ran, (
        f"{adapter}: sync and async tool wrappers disagreed (sync ran={sync_ran}, "
        f"async ran={async_ran}) — one path diverges from the other's governance verdict"
    )
    return async_ran


async def _drive_crewai(interceptor: object, ran: list[bool]) -> None:
    from agent_assembly.adapters.crewai import patch as crewai_patch

    class FakeBaseTool:
        name = "conformance_tool"

        def run(self, *_args: Any, **_kwargs: Any) -> dict[str, object]:
            ran[0] = True
            return {"ok": True}

    crewai_patch._apply_basetool_run_patch(FakeBaseTool, interceptor)
    FakeBaseTool().run(param="x")


async def _drive_agno(interceptor: object, ran: list[bool]) -> None:
    from agent_assembly.adapters.agno import patch as agno_patch

    # ``_apply_execute_patch`` governs BOTH the sync ``execute`` and the async
    # ``aexecute`` chokepoint (agno's primary async tool path). Drive each so the cell
    # exercises the async wrapper, not just its sync sibling.
    class FakeFunctionCall:
        def __init__(self) -> None:
            self.function = SimpleNamespace(name="conformance_tool")
            self.arguments = {"amount": 1}
            self.ran = False

        def execute(self, *_args: Any, **_kwargs: Any) -> str:
            self.ran = True
            return "ok"

        async def aexecute(self, *_args: Any, **_kwargs: Any) -> str:
            self.ran = True
            return "ok"

    agno_patch._apply_execute_patch(FakeFunctionCall, interceptor)

    sync_call = FakeFunctionCall()
    sync_call.execute()
    async_call = FakeFunctionCall()
    await async_call.aexecute()

    ran[0] = _assert_sync_and_async_agree("agno", sync_ran=sync_call.ran, async_ran=async_call.ran)


async def _drive_haystack(interceptor: object, ran: list[bool]) -> None:
    from agent_assembly.adapters.haystack import patch as haystack_patch

    class FakeTool:
        name = "conformance_tool"

        def invoke(self, **_kwargs: Any) -> dict[str, object]:
            ran[0] = True
            return {"ok": True}

    haystack_patch._apply_tool_invoke_patch(FakeTool, interceptor)
    FakeTool().invoke(param="x")


async def _drive_langchain(interceptor: object, ran: list[bool]) -> None:
    from agent_assembly.adapters.langchain.callback_handler import (
        AssemblyCallbackHandler,
    )

    # LangChain governs via a pre-execution callback: on_tool_start raises to abort the
    # tool. The tool "runs" iff the pre-hook returns without blocking.
    handler = AssemblyCallbackHandler(interceptor)
    handler.on_tool_start({"name": "conformance_tool"}, "input", run_id=uuid4())
    ran[0] = True


async def _drive_llamaindex(interceptor: object, ran: list[bool]) -> None:
    from agent_assembly.adapters.llamaindex import patch as llamaindex_patch

    class _Meta:
        def __init__(self, name: str) -> None:
            self._name = name

        def get_name(self) -> str:
            return self._name

    class FakeFunctionTool:
        def __init__(self) -> None:
            self.metadata = _Meta("conformance_tool")

        def call(self, *_args: Any, **_kwargs: Any) -> dict[str, object]:
            ran[0] = True
            return {"ok": True}

        async def acall(self, *_args: Any, **_kwargs: Any) -> dict[str, object]:
            ran[0] = True
            return {"ok": True}

    llamaindex_patch._apply_tool_call_patch(FakeFunctionTool, interceptor)
    FakeFunctionTool().call(param="x")


async def _drive_smolagents(interceptor: object, ran: list[bool]) -> None:
    from agent_assembly.adapters.smolagents import patch as smolagents_patch

    class FakeTool:
        name = "conformance_tool"

        def __call__(self, *_args: Any, **_kwargs: Any) -> dict[str, object]:
            ran[0] = True
            return {"ok": True}

    smolagents_patch._apply_tool_call_patch(FakeTool, interceptor)
    FakeTool()(text="x")


async def _drive_microsoft_agent_framework(interceptor: object, ran: list[bool]) -> None:
    from agent_assembly.adapters.microsoft_agent_framework import patch as maf_patch

    class FakeFunctionTool:
        name = "conformance_tool"

        async def invoke(self, *_args: Any, **_kwargs: Any) -> str:
            ran[0] = True
            return "ok"

    maf_patch._apply_function_tool_invoke_patch(FakeFunctionTool, interceptor)
    await FakeFunctionTool().invoke(arguments={"amount": 1})


async def _drive_openai_agents(interceptor: object, ran: list[bool]) -> None:
    from agent_assembly.adapters.openai_agents import patch as openai_patch

    class FakeFunctionTool:
        def __init__(self) -> None:
            self.name = "conformance_tool"

            async def _invoke(_ctx: Any, _tool_input: Any) -> dict[str, object]:
                ran[0] = True
                return {"ok": True}

            self.on_invoke_tool = _invoke

    openai_patch._apply_function_tool_patch(FakeFunctionTool, interceptor)
    tool = FakeFunctionTool()
    await tool.on_invoke_tool(SimpleNamespace(agent_id="conformance-agent"), "{}")


async def _drive_pydantic_ai(interceptor: object, ran: list[bool]) -> None:
    from agent_assembly.adapters.pydantic_ai import patch as pydantic_ai_patch

    # The pinned/shipped Pydantic AI line (>=0.3.0) routes tool execution through
    # ``AbstractToolset.call_tool`` — the <0.3.0 ``Tool._run`` hook this cell used to
    # drive does NOT exist there, so it exercised a wrapper the shipped framework never
    # runs. Drive the toolset hook (``_apply_toolset_call_tool_patch``) with its real
    # ``(self, name, tool_args, ctx, tool)`` signature so the cell tests what ships.
    class FakeToolset:
        async def call_tool(self, name: Any, tool_args: Any, ctx: Any, tool: Any, **_kwargs: Any) -> dict[str, object]:
            ran[0] = True
            return {"ok": True}

    pydantic_ai_patch._apply_toolset_call_tool_patch(FakeToolset, interceptor)
    ctx = SimpleNamespace(
        deps=SimpleNamespace(assembly_agent_id="conformance-agent"),
        run_id="run-1",
    )
    await FakeToolset().call_tool(
        "conformance_tool",
        {"topic": "x"},
        ctx,
        SimpleNamespace(name="conformance_tool"),
    )


async def _drive_google_adk(interceptor: object, ran: list[bool]) -> None:
    from agent_assembly.adapters.google_adk import patch as google_adk_patch

    class FakeBaseTool:
        name = "conformance_tool"

        async def run_async(self, *, args: Any, tool_context: Any, **_kwargs: Any) -> dict[str, object]:
            del args, tool_context
            ran[0] = True
            return {"ok": True}

    google_adk_patch._apply_tool_run_async_patch(FakeBaseTool, interceptor)
    tool_context = SimpleNamespace(
        invocation_context=SimpleNamespace(assembly_agent_id="conformance-agent", invocation_id="run-1"),
    )
    await FakeBaseTool().run_async(args={"step": 1}, tool_context=tool_context)


async def _drive_mcp(interceptor: object, ran: list[bool]) -> None:
    from agent_assembly.adapters.mcp import patch as mcp_patch

    class FakeClientSession:
        _server_name = "conformance-server"

        async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, object]:
            del name, arguments
            ran[0] = True
            return {"ok": True}

    mcp_patch._apply_client_session_patch(FakeClientSession, interceptor)
    session = FakeClientSession()
    await session.call_tool("conformance_tool", {"q": "x"})


# adapter package name → driver. The key MUST equal the directory under
# ``agent_assembly/adapters/`` (the completeness test enforces this both ways).
DRIVERS: dict[str, Driver] = {
    "agno": _drive_agno,
    "crewai": _drive_crewai,
    "google_adk": _drive_google_adk,
    "haystack": _drive_haystack,
    "langchain": _drive_langchain,
    "llamaindex": _drive_llamaindex,
    "mcp": _drive_mcp,
    "microsoft_agent_framework": _drive_microsoft_agent_framework,
    "openai_agents": _drive_openai_agents,
    "pydantic_ai": _drive_pydantic_ai,
    "smolagents": _drive_smolagents,
}

# Adapter packages that intentionally have no pre-execution tool-gate driver, each
# with the reason. If one of these grows a tool gate, delete its exemption and add a
# driver; if a brand-new adapter package appears, the completeness test fails until it
# gets a driver or a justified exemption here — that is the anti-whack-a-mole guard.
EXEMPT_ADAPTERS: dict[str, str] = {
    "langgraph": "lineage-only: patches node/graph lifecycle for edge emission, no pre-execution tool deny gate",
    "_shared": "shared async governance helper reused by other adapters, not a framework adapter itself",
}


def discover_adapter_packages() -> set[str]:
    """Return the adapter package directories present under ``agent_assembly/adapters/``.

    A package is a subdirectory with an ``__init__.py`` (this includes ``_shared``);
    dunder dirs such as ``__pycache__`` are excluded.
    """
    adapters_pkg = importlib.import_module("agent_assembly.adapters")
    adapters_dir = Path(adapters_pkg.__file__).parent  # type: ignore[arg-type]
    return {
        entry.name
        for entry in adapters_dir.iterdir()
        if entry.is_dir() and not entry.name.startswith("__") and (entry / "__init__.py").exists()
    }


async def run_scenario(adapter_name: str, scenario: str, mode: str | None) -> bool:
    """Drive one adapter through one scenario under one mode; return whether the tool ran.

    A blocked-by-raise deny (PolicyViolationError / ToolExecutionBlockedError /
    MCPToolBlockedError — all ``AssemblyError`` subclasses) is swallowed here because
    it is the intended block outcome; the ``ran`` flag is the sole signal. Any other
    exception propagates and fails the test.
    """
    from agent_assembly.exceptions import AssemblyError

    enforce = _local_posture_is_enforce(mode)
    interceptor = make_fake_interceptor(scenario, enforce=enforce)
    ran = [False]
    with contextlib.suppress(AssemblyError):
        await DRIVERS[adapter_name](interceptor, ran)
    return ran[0]
