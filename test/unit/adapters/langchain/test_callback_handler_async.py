"""Async-dispatch coverage for ``AssemblyCallbackHandler``.

LangChain decides whether to run a callback sync or async by looking the
``on_*`` method up on the handler and testing ``inspect.iscoroutinefunction``
on it. ``AssemblyCallbackHandler`` defines every ``on_*`` method **sync**, so
under an async agent the async callback manager runs those *sync* methods in a
thread executor via ``ahandle_event`` — there is no separate ``aon_*`` code
path (an earlier set of ``aon_*`` methods was dead and removed in AAASM-4710).

These tests therefore drive the **real async manager** (``ahandle_event``)
against the sync handler, rather than calling handler methods directly, and
assert that governance still enforces across that async path. They need the
real ``langchain_core`` base class, so the module is guarded by
``importorskip`` and runs under the ``langchain-test`` dependency group:

    uv sync --group langchain-test
    .venv/bin/python -m pytest \
        test/unit/adapters/langchain/test_callback_handler_async.py
"""

from __future__ import annotations

from uuid import uuid4

import pytest

pytest.importorskip("langchain_core")

from langchain_core.callbacks.manager import ahandle_event  # noqa: E402

from agent_assembly.adapters.langchain import AssemblyCallbackHandler  # noqa: E402
from agent_assembly.exceptions import ToolExecutionBlockedError  # noqa: E402


class SyncInterceptor:
    """Sync governance interceptor.

    The handler's ``on_tool_start`` calls ``check_tool_start`` **without
    awaiting**, so the wired interceptor is sync even when the dispatch that
    reaches it is async — that coupling is exactly what these tests exercise.
    """

    def __init__(self) -> None:
        self.tool_start_calls = 0
        self.pending_wait_calls = 0

    def check_tool_start(self, **kwargs: object) -> object:
        self.tool_start_calls += 1
        return kwargs.get("decision", {"status": "allow"})

    def wait_for_tool_approval(self, **kwargs: object) -> object:
        self.pending_wait_calls += 1
        return kwargs.get("approval_decision", {"status": "allow"})


class _EnforcingSyncInterceptor(SyncInterceptor):
    """SyncInterceptor carrying the fail-closed enforce posture (AAASM-3106)."""

    _enforce = True


async def _dispatch_tool_start(handler: AssemblyCallbackHandler, **kwargs: object) -> None:
    """Fire ``on_tool_start`` through the real async callback manager.

    ``ahandle_event`` is the async dispatcher LangChain uses for an async run;
    it runs the sync ``on_tool_start`` in an executor and — because the handler
    sets ``raise_error=True`` — re-raises a ``ToolExecutionBlockedError`` from
    the callback instead of swallowing it.
    """
    await ahandle_event(
        [handler],
        "on_tool_start",
        None,
        {"name": "web_search"},
        "query",
        run_id=uuid4(),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_async_dispatch_blocks_on_deny() -> None:
    interceptor = SyncInterceptor()
    handler = AssemblyCallbackHandler(interceptor)

    with pytest.raises(ToolExecutionBlockedError):
        await _dispatch_tool_start(handler, decision={"status": "deny", "reason": "blocked"})

    assert interceptor.tool_start_calls == 1, "sync handler was not reached via the async manager"


@pytest.mark.asyncio
async def test_async_dispatch_allows_on_allow() -> None:
    interceptor = SyncInterceptor()
    handler = AssemblyCallbackHandler(interceptor)

    await _dispatch_tool_start(handler, decision={"status": "allow"})

    assert interceptor.tool_start_calls == 1


@pytest.mark.asyncio
async def test_async_dispatch_waits_for_pending_approval() -> None:
    interceptor = SyncInterceptor()
    handler = AssemblyCallbackHandler(interceptor)

    await _dispatch_tool_start(
        handler,
        decision={"status": "pending"},
        approval_decision={"status": "allow"},
    )

    assert interceptor.pending_wait_calls == 1


# --- AAASM-3107: unknown/None/malformed verdicts must fail closed under enforce ---


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", [None, "maybe", 12345, {"status": "garbage"}, {}])
async def test_async_dispatch_denies_unknown_under_enforce(decision: object) -> None:
    handler = AssemblyCallbackHandler(_EnforcingSyncInterceptor())

    with pytest.raises(ToolExecutionBlockedError):
        await _dispatch_tool_start(handler, decision=decision)


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", [None, "maybe", 12345, {"status": "garbage"}, {}])
async def test_async_dispatch_allows_unknown_when_not_enforcing(decision: object) -> None:
    interceptor = SyncInterceptor()
    handler = AssemblyCallbackHandler(interceptor)

    await _dispatch_tool_start(handler, decision=decision)

    assert interceptor.pending_wait_calls == 0
