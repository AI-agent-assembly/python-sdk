from __future__ import annotations

from uuid import uuid4

import pytest

from agent_assembly.adapters.langchain import AssemblyCallbackHandler
from agent_assembly.exceptions import ToolExecutionBlockedError


class SyncInterceptor:
    def __init__(self) -> None:
        self.tool_end_calls = 0
        self.llm_scan_calls = 0
        self.llm_end_calls = 0
        self.pending_wait_calls = 0
        self.last_prompts: list[str] | None = None

    def check_tool_start(self, **kwargs: object) -> object:
        return kwargs.get("decision", {"status": "allow"})

    def wait_for_tool_approval(self, **kwargs: object) -> object:
        self.pending_wait_calls += 1
        return kwargs.get("approval_decision", {"status": "allow"})

    def on_tool_end(self, **kwargs: object) -> None:
        self.tool_end_calls += 1

    def on_llm_start_scan(self, **kwargs: object) -> None:
        self.llm_scan_calls += 1
        prompts = kwargs.get("prompts")
        if isinstance(prompts, list):
            self.last_prompts = prompts

    def on_llm_end(self, **kwargs: object) -> None:
        self.llm_end_calls += 1


def test_on_tool_start_raises_when_governance_denies() -> None:
    handler = AssemblyCallbackHandler(SyncInterceptor())

    with pytest.raises(ToolExecutionBlockedError):
        handler.on_tool_start(
            serialized={"name": "web_search"},
            input_str="query",
            run_id=uuid4(),
            decision={"status": "deny", "reason": "blocked"},
        )


def test_on_tool_start_waits_for_pending_approval() -> None:
    interceptor = SyncInterceptor()
    handler = AssemblyCallbackHandler(interceptor)

    handler.on_tool_start(
        serialized={"name": "calendar_write"},
        input_str="create event",
        run_id=uuid4(),
        decision={"status": "pending"},
        approval_decision={"status": "allow"},
    )

    assert interceptor.pending_wait_calls == 1


def test_on_tool_start_blocks_when_pending_never_approved() -> None:
    handler = AssemblyCallbackHandler(SyncInterceptor())

    with pytest.raises(ToolExecutionBlockedError):
        handler.on_tool_start(
            serialized={"name": "calendar_write"},
            input_str="create event",
            run_id=uuid4(),
            decision={"status": "pending"},
            approval_decision={"status": "deny"},
        )


def test_on_tool_end_delegates_to_interceptor() -> None:
    interceptor = SyncInterceptor()
    handler = AssemblyCallbackHandler(interceptor)

    handler.on_tool_end(output={"ok": True}, run_id=uuid4())

    assert interceptor.tool_end_calls == 1


def test_on_llm_start_scans_without_mutating_prompts() -> None:
    interceptor = SyncInterceptor()
    handler = AssemblyCallbackHandler(interceptor)
    prompts = ["hello", "world"]

    handler.on_llm_start(
        serialized={"name": "gpt"},
        prompts=prompts,
        run_id=uuid4(),
    )

    assert interceptor.llm_scan_calls == 1
    assert interceptor.last_prompts is prompts
    assert prompts == ["hello", "world"]


def test_on_llm_end_delegates_to_interceptor() -> None:
    interceptor = SyncInterceptor()
    handler = AssemblyCallbackHandler(interceptor)

    handler.on_llm_end(response={"text": "done"}, run_id=uuid4())

    assert interceptor.llm_end_calls == 1
