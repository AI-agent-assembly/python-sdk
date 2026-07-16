from __future__ import annotations

from uuid import uuid4

import pytest

from agent_assembly.adapters.langchain import AssemblyCallbackHandler
from agent_assembly.exceptions import ToolExecutionBlockedError


class AsyncInterceptor:
    def __init__(self) -> None:
        self.tool_end_calls = 0
        self.llm_scan_calls = 0
        self.llm_end_calls = 0
        self.pending_wait_calls = 0

    async def check_tool_start(self, **kwargs: object) -> object:
        return kwargs.get("decision", {"status": "allow"})

    async def wait_for_tool_approval(self, **kwargs: object) -> object:
        self.pending_wait_calls += 1
        return kwargs.get("approval_decision", {"status": "allow"})

    async def on_tool_end(self, **kwargs: object) -> None:
        self.tool_end_calls += 1

    async def on_llm_start_scan(self, **kwargs: object) -> None:
        self.llm_scan_calls += 1

    async def on_llm_end(self, **kwargs: object) -> None:
        self.llm_end_calls += 1


@pytest.mark.asyncio
async def test_aon_tool_start_raises_when_governance_denies() -> None:
    handler = AssemblyCallbackHandler(AsyncInterceptor())
    run_id = uuid4()

    with pytest.raises(ToolExecutionBlockedError):
        await handler.aon_tool_start(
            serialized={"name": "web_search"},
            input_str="query",
            run_id=run_id,
            decision={"status": "deny", "reason": "blocked"},
        )


@pytest.mark.asyncio
async def test_aon_tool_start_waits_for_pending_approval() -> None:
    interceptor = AsyncInterceptor()
    handler = AssemblyCallbackHandler(interceptor)

    await handler.aon_tool_start(
        serialized={"name": "calendar_write"},
        input_str="create event",
        run_id=uuid4(),
        decision={"status": "pending"},
        approval_decision={"status": "allow"},
    )

    assert interceptor.pending_wait_calls == 1


@pytest.mark.asyncio
async def test_aon_tool_end_delegates_to_interceptor() -> None:
    interceptor = AsyncInterceptor()
    handler = AssemblyCallbackHandler(interceptor)

    await handler.aon_tool_end(output={"ok": True}, run_id=uuid4())

    assert interceptor.tool_end_calls == 1


@pytest.mark.asyncio
async def test_aon_llm_start_delegates_to_interceptor() -> None:
    interceptor = AsyncInterceptor()
    handler = AssemblyCallbackHandler(interceptor)

    await handler.aon_llm_start(
        serialized={"name": "gpt"},
        prompts=["hello", "world"],
        run_id=uuid4(),
    )

    assert interceptor.llm_scan_calls == 1


@pytest.mark.asyncio
async def test_aon_llm_end_delegates_to_interceptor() -> None:
    interceptor = AsyncInterceptor()
    handler = AssemblyCallbackHandler(interceptor)

    await handler.aon_llm_end(response={"text": "done"}, run_id=uuid4())

    assert interceptor.llm_end_calls == 1


class _EnforcingAsyncInterceptor(AsyncInterceptor):
    """AsyncInterceptor carrying the fail-closed enforce posture (AAASM-3106)."""

    _enforce = True


# --- AAASM-3107: unknown/None/malformed verdicts must fail closed under enforce ---


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", [None, "maybe", 12345, {"status": "garbage"}, {}])
async def test_aon_tool_start_denies_unknown_under_enforce(decision: object) -> None:
    handler = AssemblyCallbackHandler(_EnforcingAsyncInterceptor())
    run_id = uuid4()

    with pytest.raises(ToolExecutionBlockedError):
        await handler.aon_tool_start(
            serialized={"name": "web_search"},
            input_str="query",
            run_id=run_id,
            decision=decision,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", [None, "maybe", 12345, {"status": "garbage"}, {}])
async def test_aon_tool_start_allows_unknown_when_not_enforcing(decision: object) -> None:
    interceptor = AsyncInterceptor()
    handler = AssemblyCallbackHandler(interceptor)

    await handler.aon_tool_start(
        serialized={"name": "web_search"},
        input_str="query",
        run_id=uuid4(),
        decision=decision,
    )

    assert interceptor.pending_wait_calls == 0
