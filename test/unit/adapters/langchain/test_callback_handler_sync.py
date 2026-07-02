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


def test_on_tool_start_allows_when_governance_allows() -> None:
    interceptor = SyncInterceptor()
    handler = AssemblyCallbackHandler(interceptor)

    handler.on_tool_start(
        serialized={"name": "web_search"},
        input_str="query",
        run_id=uuid4(),
        decision={"status": "allow"},
    )

    assert interceptor.pending_wait_calls == 0


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


class _EnforcingInterceptor(SyncInterceptor):
    """SyncInterceptor carrying the fail-closed enforce posture (AAASM-3106)."""

    _enforce = True


# --- AAASM-3107: unknown/None/malformed verdicts must fail closed under enforce ---


@pytest.mark.parametrize(
    "decision",
    [
        None,
        "maybe",
        12345,
        {"status": "garbage"},
        {},
    ],
)
def test_unknown_decision_denies_under_enforce(decision: object) -> None:
    handler = AssemblyCallbackHandler(_EnforcingInterceptor())

    with pytest.raises(ToolExecutionBlockedError):
        handler.on_tool_start(
            serialized={"name": "web_search"},
            input_str="query",
            run_id=uuid4(),
            decision=decision,
        )


@pytest.mark.parametrize(
    "decision",
    [
        None,
        "maybe",
        12345,
        {"status": "garbage"},
        {},
    ],
)
def test_unknown_decision_allows_when_not_enforcing(decision: object) -> None:
    interceptor = SyncInterceptor()
    handler = AssemblyCallbackHandler(interceptor)

    handler.on_tool_start(
        serialized={"name": "web_search"},
        input_str="query",
        run_id=uuid4(),
        decision=decision,
    )

    assert interceptor.pending_wait_calls == 0


def test_known_verdicts_unchanged_under_enforce() -> None:
    handler = AssemblyCallbackHandler(_EnforcingInterceptor())

    assert handler._normalize_decision("allow") == ("allow", None)
    assert handler._normalize_decision({"status": "deny", "reason": "nope"}) == ("deny", "nope")
    assert handler._normalize_decision("pending") == ("pending", None)


# --- AAASM-4014: delegate governance entry points to the wrapped interceptor ---


def test_delegates_check_tool_start_to_interceptor() -> None:
    """A co-installed adapter looking up ``check_tool_start`` on the handler must
    reach the wrapped interceptor rather than getting ``None`` (AAASM-4014)."""
    interceptor = SyncInterceptor()
    handler = AssemblyCallbackHandler(interceptor)

    method = getattr(handler, "check_tool_start", None)
    assert callable(method)
    assert method(decision={"status": "deny", "reason": "blocked"}) == {"status": "deny", "reason": "blocked"}


def test_delegates_arbitrary_interceptor_attributes() -> None:
    """Non-callback governance entry points (approval, timeout provider, event
    reporting) are forwarded to the wrapped interceptor too."""

    class _RichInterceptor:
        pending_tool_approval_timeout_seconds = 42

        def wait_for_tool_approval(self, **_kwargs: object) -> dict[str, str]:
            return {"status": "allow"}

    handler = AssemblyCallbackHandler(_RichInterceptor())

    assert callable(getattr(handler, "wait_for_tool_approval", None))
    assert handler.pending_tool_approval_timeout_seconds == 42


def test_missing_attribute_raises_attribute_error() -> None:
    """Delegation does not synthesize unknown attributes; a genuinely missing
    name still raises ``AttributeError`` (no unbounded recursion)."""
    handler = AssemblyCallbackHandler(SyncInterceptor())

    with pytest.raises(AttributeError):
        handler.definitely_not_defined  # noqa: B018


def test_explicit_callback_methods_are_not_delegated() -> None:
    """The LangChain callback contract defined on the handler takes precedence
    over delegation so LangChain's own dispatch is unaffected."""
    interceptor = SyncInterceptor()
    handler = AssemblyCallbackHandler(interceptor)

    handler.on_tool_end(output="done", run_id=uuid4())

    assert interceptor.tool_end_calls == 1
