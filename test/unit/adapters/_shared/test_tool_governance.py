"""Regression tests for the shared async tool-governance flow.

These pin the fail-closed guarantee of ``run_governed_async_tool``: only an
explicit ``allow`` verdict may run the wrapped tool. A terminal ``pending``
verdict (approval round-trip that resolves to ``pending`` again) is a
non-decision and must block, mirroring the LangChain handler (AAASM-4898).
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_assembly.adapters._shared import tool_governance
from agent_assembly.exceptions import PolicyViolationError


class _TerminalPendingHandler:
    def check_tool_start(self, **kwargs: Any) -> dict[str, str]:
        del kwargs
        return {"status": "pending", "reason": "awaiting approval"}

    def wait_for_tool_approval(self, **kwargs: Any) -> dict[str, str]:
        del kwargs
        return {"status": "pending", "reason": "still pending"}


@pytest.mark.asyncio
async def test_terminal_pending_blocks_and_never_invokes_original() -> None:
    handler = _TerminalPendingHandler()
    ran: list[bool] = []

    def invoke_original() -> str:
        ran.append(True)
        return "tool-result"

    with pytest.raises(PolicyViolationError, match="rejected during approval"):
        await tool_governance.run_governed_async_tool(
            handler,
            enforce=True,
            tool_name="fake_tool",
            tool_args={"text": "hi"},
            agent_id="agent-1",
            run_id=None,
            invoke_original=invoke_original,
        )

    assert ran == []


class _FourKeywordHandler:
    """A handler written against the pre-AAASM-5665 four-keyword hook.

    No ``denied`` parameter and no ``**kwargs``, so passing the flag to it would
    raise ``TypeError``. Every in-tree adapter hook and any third-party one
    predates the flag, which is why the flag is offered conditionally.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def record_result(self, *, tool_name: str, result: str, agent_id: str | None, run_id: str | None) -> None:
        self.calls.append({"tool_name": tool_name, "result": result, "agent_id": agent_id, "run_id": run_id})


class _UnreadableSignatureHook:
    """A callable whose signature cannot be introspected.

    ``inspect.signature`` raises ``ValueError`` for C-implemented callables
    (``dict`` and ``type`` do so on CPython), and proxy/wrapper objects
    reproduce it by raising from ``__signature__``. Either way the SDK cannot
    prove the callable accepts the flag, so it must fall back to the narrow
    call rather than risk a ``TypeError`` that would swallow the deny.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)

    @property
    def __signature__(self) -> Any:
        raise ValueError("no signature found for builtin")


class _DenyingHandlerMixin:
    def check_tool_start(self, **kwargs: Any) -> dict[str, str]:
        del kwargs
        return {"status": "deny", "reason": "policy forbids this tool"}


class _FourKeywordDenyHandler(_DenyingHandlerMixin, _FourKeywordHandler):
    pass


class _UnreadableSignatureDenyHandler(_DenyingHandlerMixin):
    def __init__(self) -> None:
        self.record_result = _UnreadableSignatureHook()


async def _run_denied(handler: Any) -> None:
    ran: list[bool] = []

    def invoke_original() -> str:
        ran.append(True)
        return "tool-result"

    with pytest.raises(PolicyViolationError, match="policy forbids this tool"):
        await tool_governance.run_governed_async_tool(
            handler,
            enforce=True,
            tool_name="write_to_disk",
            tool_args={"path": "/tmp/x"},
            agent_id="agent-1",
            run_id="run-1",
            invoke_original=invoke_original,
        )

    assert ran == [], "the denied tool body ran"


@pytest.mark.asyncio
async def test_a_four_keyword_handler_still_receives_the_deny_record_without_the_flag() -> None:
    """Reads the arguments the flow passed the handler's own record_result.

    This is the backward-compatibility guarantee: adding ``denied`` must not
    stop a handler that predates it from being recorded to. If the flag were
    passed unconditionally this call would raise ``TypeError`` from inside the
    governance flow and replace the policy denial with an unrelated error.
    """
    handler = _FourKeywordDenyHandler()

    await _run_denied(handler)

    assert len(handler.calls) == 1
    call = handler.calls[0]
    assert call["tool_name"] == "write_to_disk"
    assert call["agent_id"] == "agent-1"
    assert call["run_id"] == "run-1"
    assert "policy forbids this tool" in call["result"]
    # The flag is absent rather than False: the handler cannot receive it.
    assert "denied" not in call


@pytest.mark.asyncio
async def test_a_hook_with_no_readable_signature_still_receives_the_deny_record() -> None:
    """Reads the keywords the flow passed an unintrospectable callable hook."""
    handler = _UnreadableSignatureDenyHandler()

    await _run_denied(handler)

    assert len(handler.record_result.calls) == 1
    call = handler.record_result.calls[0]
    assert call["tool_name"] == "write_to_disk"
    assert call["run_id"] == "run-1"
    # Narrow call: the flag is withheld because acceptance could not be proven.
    assert "denied" not in call
