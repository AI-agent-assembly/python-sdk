from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters.crewai import patch as crewai_patch


class _RecordingInterceptor:
    def check_tool_start(self, **kwargs: object) -> dict[str, str]:
        del kwargs
        return {"status": "allow"}


def _install_fake_crewai_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[type[Any], type[Any]]:
    class FakeBaseTool:
        name = "fake_tool"

        def run(self, *args: Any, **kwargs: Any) -> dict[str, object]:
            return {"args": args, "kwargs": kwargs}

    class FakeTask:
        description = "fake task"
        expected_output = "fake output"

        def execute_sync(self, *args: Any, **kwargs: Any) -> dict[str, object]:
            return {"args": args, "kwargs": kwargs}

    fake_crewai_tools = SimpleNamespace(BaseTool=FakeBaseTool)
    fake_crewai_module = SimpleNamespace(Task=FakeTask)

    def fake_import_module(module_name: str) -> object:
        if module_name == "crewai.tools":
            return fake_crewai_tools
        if module_name == "crewai":
            return fake_crewai_module
        raise ImportError(module_name)

    monkeypatch.setattr(crewai_patch.importlib, "import_module", fake_import_module)
    return FakeBaseTool, FakeTask


def test_apply_patches_crewai_run_and_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBaseTool, FakeTask = _install_fake_crewai_modules(monkeypatch)

    patcher = crewai_patch.CrewAIPatch(_RecordingInterceptor())
    assert patcher.apply() is True
    first_run_ref = FakeBaseTool.run
    first_task_ref = FakeTask.execute_sync

    assert getattr(FakeBaseTool, crewai_patch._TOOLS_PATCHED_FLAG, False) is True
    assert getattr(FakeTask, crewai_patch._TASK_PATCHED_FLAG, False) is True

    assert patcher.apply() is True
    assert FakeBaseTool.run is first_run_ref
    assert FakeTask.execute_sync is first_task_ref


def test_revert_restores_crewai_runtime_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBaseTool, FakeTask = _install_fake_crewai_modules(monkeypatch)
    original_run = FakeBaseTool.run
    original_execute_sync = FakeTask.execute_sync

    patcher = crewai_patch.CrewAIPatch(_RecordingInterceptor())
    assert patcher.apply() is True
    assert FakeBaseTool.run is not original_run
    assert FakeTask.execute_sync is not original_execute_sync

    patcher.revert()
    assert FakeBaseTool.run is original_run
    assert FakeTask.execute_sync is original_execute_sync
    assert getattr(FakeBaseTool, crewai_patch._TOOLS_PATCHED_FLAG, False) is False
    assert getattr(FakeTask, crewai_patch._TASK_PATCHED_FLAG, False) is False


def test_loader_edge_cases_and_apply_false_without_basetool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_import_error(module_name: str) -> object:
        raise ImportError(module_name)

    monkeypatch.setattr(crewai_patch.importlib, "import_module", raise_import_error)
    assert crewai_patch._load_crewai_basetool_class() is None
    assert crewai_patch._load_crewai_task_class() is None
    assert crewai_patch.CrewAIPatch(_RecordingInterceptor()).apply() is False

    fake_crewai_tools = SimpleNamespace(BaseTool=object())
    fake_crewai_module = SimpleNamespace(Task=object())

    def return_non_type(module_name: str) -> object:
        if module_name == "crewai.tools":
            return fake_crewai_tools
        if module_name == "crewai":
            return fake_crewai_module
        raise ImportError(module_name)

    monkeypatch.setattr(crewai_patch.importlib, "import_module", return_non_type)
    assert crewai_patch._load_crewai_basetool_class() is None
    assert crewai_patch._load_crewai_task_class() is None


def test_helper_branch_coverage_for_decision_and_agent_extraction() -> None:
    assert crewai_patch._normalize_decision("deny") == ("deny", None)
    assert crewai_patch._normalize_decision("pending") == ("pending", None)
    assert crewai_patch._normalize_decision("allow") == ("allow", None)
    assert crewai_patch._normalize_decision(12345) == ("allow", None)

    assert crewai_patch._extract_agent_id_from_inputs((), {"agent_id": "agent-direct"}) == "agent-direct"
    assert (
        crewai_patch._extract_agent_id_from_inputs(
            (),
            {"config": {"configurable": {"agent_id": "agent-configurable"}}},
        )
        == "agent-configurable"
    )
    assert (
        crewai_patch._extract_agent_id_from_inputs(
            (),
            {"config": {"metadata": {"agent_id": "agent-metadata"}}},
        )
        == "agent-metadata"
    )
    assert crewai_patch._extract_agent_id_from_inputs(({"agent_id": "agent-state"},), {}) == "agent-state"
    assert crewai_patch._extract_agent_id_from_inputs((), {}) is None

    class NoHandlers:
        pass

    fallback_check = crewai_patch._invoke_sync_tool_check(
        NoHandlers(),
        tool_name="x",
        tool_args={},
        agent_id=None,
    )
    assert fallback_check == {"status": "allow"}

    fallback_wait = crewai_patch._wait_for_sync_tool_approval(
        NoHandlers(),
        tool_name="x",
        timeout_seconds=1,
        tool_args={},
        agent_id=None,
    )
    assert fallback_wait == {"status": "deny", "reason": "Approval handler is unavailable."}

    class TimeoutProvider:
        def get_pending_tool_approval_timeout_seconds(self) -> str:
            return "42"

    assert crewai_patch._get_pending_tool_approval_timeout_seconds(TimeoutProvider()) == 42
    assert (
        crewai_patch._get_pending_tool_approval_timeout_seconds(
            SimpleNamespace(pending_tool_approval_timeout_seconds=0)
        )
        == 300
    )
    assert (
        crewai_patch._get_pending_tool_approval_timeout_seconds(
            SimpleNamespace(pending_tool_approval_timeout_seconds=True)
        )
        == 300
    )


def test_record_result_and_task_fallback_handlers_are_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeBaseTool:
        name = "record_result_tool"

        def run(self, *args: Any, **kwargs: Any) -> dict[str, object]:
            return {"args": args, "kwargs": kwargs}

    class FakeTask:
        description = "fallback task"
        expected_output = "fallback output"

        def execute_sync(self, *args: Any, **kwargs: Any) -> str:
            del args, kwargs
            return "task-result"

    fake_crewai_tools = SimpleNamespace(BaseTool=FakeBaseTool)
    fake_crewai_module = SimpleNamespace(Task=FakeTask)

    def fake_import_module(module_name: str) -> object:
        if module_name == "crewai.tools":
            return fake_crewai_tools
        if module_name == "crewai":
            return fake_crewai_module
        raise ImportError(module_name)

    monkeypatch.setattr(crewai_patch.importlib, "import_module", fake_import_module)

    seen_results: list[object] = []
    lifecycle_events: list[str] = []

    class FallbackInterceptor:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "allow"}

        def record_result(self, **kwargs: object) -> None:
            seen_results.append(kwargs["result"])

        def on_task_start(self, **kwargs: object) -> None:
            del kwargs
            lifecycle_events.append("start")

        def on_task_complete(self, **kwargs: object) -> None:
            del kwargs
            lifecycle_events.append("complete")

    patcher = crewai_patch.CrewAIPatch(FallbackInterceptor())
    assert patcher.apply() is True

    tool_result = FakeBaseTool().run(alpha=1)
    task_result = FakeTask().execute_sync()

    assert tool_result == {"args": (), "kwargs": {"alpha": 1}}
    assert seen_results == [tool_result]
    assert task_result == "task-result"
    assert lifecycle_events == ["start", "complete"]


# --- AAASM-3107: unknown/None/malformed verdicts must fail closed under enforce ---


@pytest.mark.parametrize("decision", [None, "maybe", 12345, {"status": "garbage"}, {}])
def test_normalize_decision_denies_unknown_under_enforce(decision: object) -> None:
    status, reason = crewai_patch._normalize_decision(decision, enforce=True)
    assert status == "deny"
    assert reason


@pytest.mark.parametrize("decision", [None, "maybe", 12345, {"status": "garbage"}, {}])
def test_normalize_decision_allows_unknown_when_not_enforcing(decision: object) -> None:
    assert crewai_patch._normalize_decision(decision, enforce=False) == ("allow", None)


def test_normalize_decision_known_verdicts_unchanged_under_enforce() -> None:
    assert crewai_patch._normalize_decision("allow", enforce=True) == ("allow", None)
    assert crewai_patch._normalize_decision("deny", enforce=True) == ("deny", None)
    assert crewai_patch._normalize_decision("pending", enforce=True) == ("pending", None)
    assert crewai_patch._normalize_decision({"status": "deny", "reason": "x"}, enforce=True) == ("deny", "x")


def test_interceptor_enforces_reads_enforce_flag() -> None:
    assert crewai_patch._interceptor_enforces(SimpleNamespace(_enforce=True)) is True
    assert crewai_patch._interceptor_enforces(SimpleNamespace()) is False
    assert crewai_patch._interceptor_enforces(SimpleNamespace(_interceptor=SimpleNamespace(_enforce=True))) is True


def test_unknown_verdict_blocks_tool_under_enforce(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBaseTool, _ = _install_fake_crewai_modules(monkeypatch)

    class EnforcingUnknownInterceptor:
        _enforce = True

        def check_tool_start(self, **kwargs: object) -> object:
            del kwargs
            return None

    patcher = crewai_patch.CrewAIPatch(EnforcingUnknownInterceptor())
    assert patcher.apply() is True

    result = FakeBaseTool().run(param="value")

    assert isinstance(result, str)
    assert "[BLOCKED by governance policy]" in result


def test_blocked_tool_returns_policy_string(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBaseTool, _ = _install_fake_crewai_modules(monkeypatch)

    class BlockInterceptor:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "deny", "reason": "blocked for safety"}

    patcher = crewai_patch.CrewAIPatch(BlockInterceptor())
    assert patcher.apply() is True

    tool = FakeBaseTool()
    result = tool.run(param="value")

    assert isinstance(result, str)
    assert "[BLOCKED by governance policy]" in result
    assert "blocked for safety" in result


def test_allowed_tool_runs_and_records_result(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBaseTool, _ = _install_fake_crewai_modules(monkeypatch)
    observed: list[object] = []

    class AllowInterceptor:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "allow"}

        def on_tool_end(self, *, output: object, **kwargs: object) -> None:
            del kwargs
            observed.append(output)

    patcher = crewai_patch.CrewAIPatch(AllowInterceptor())
    assert patcher.apply() is True

    tool = FakeBaseTool()
    result = tool.run(param="value")

    assert result == {"args": (), "kwargs": {"param": "value"}}
    assert observed == [result]


def test_pending_tool_waits_and_allows_when_approved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeBaseTool, _ = _install_fake_crewai_modules(monkeypatch)
    wait_calls: list[dict[str, object]] = []

    class PendingThenApproveInterceptor:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "pending", "reason": "needs approval"}

        def wait_for_tool_approval(self, **kwargs: object) -> dict[str, str]:
            wait_calls.append(dict(kwargs))
            return {"status": "allow"}

    patcher = crewai_patch.CrewAIPatch(PendingThenApproveInterceptor())
    assert patcher.apply() is True

    tool = FakeBaseTool()
    result = tool.run(param="value")

    assert result == {"args": (), "kwargs": {"param": "value"}}
    assert len(wait_calls) == 1
    assert wait_calls[0]["timeout_seconds"] == 300


def test_pending_tool_uses_configurable_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBaseTool, _ = _install_fake_crewai_modules(monkeypatch)
    wait_calls: list[dict[str, object]] = []

    class PendingWithConfigurableTimeoutInterceptor:
        pending_tool_approval_timeout_seconds = 37

        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "pending", "reason": "needs approval"}

        def wait_for_tool_approval(self, **kwargs: object) -> dict[str, str]:
            wait_calls.append(dict(kwargs))
            return {"status": "allow"}

    patcher = crewai_patch.CrewAIPatch(PendingWithConfigurableTimeoutInterceptor())
    assert patcher.apply() is True

    tool = FakeBaseTool()
    result = tool.run(param="value")

    assert result == {"args": (), "kwargs": {"param": "value"}}
    assert len(wait_calls) == 1
    assert wait_calls[0]["timeout_seconds"] == 37


def test_pending_timeout_returns_denied_string(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeBaseTool, _ = _install_fake_crewai_modules(monkeypatch)

    class PendingTimeoutInterceptor:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "pending", "reason": "requires manual approval"}

        def wait_for_tool_approval(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "deny", "reason": "approval timeout"}

    patcher = crewai_patch.CrewAIPatch(PendingTimeoutInterceptor())
    assert patcher.apply() is True

    tool = FakeBaseTool()
    result = tool.run(param="value")

    assert isinstance(result, str)
    assert result.startswith("[APPROVAL REJECTED]")
    assert "approval timeout" in result


def test_terminal_pending_blocks_tool_and_does_not_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AAASM-4898: a still-"pending" verdict after the approval round-trip must
    block, not fall through and run the tool. "pending" is a terminal
    non-decision here, so it fails closed like the LangChain handler."""
    FakeBaseTool, _ = _install_fake_crewai_modules(monkeypatch)
    recorded_results: list[object] = []

    class TerminalPendingInterceptor:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "pending", "reason": "awaiting approval"}

        def wait_for_tool_approval(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "pending", "reason": "still pending"}

        def record_result(self, **kwargs: object) -> None:
            recorded_results.append(kwargs.get("result"))

    patcher = crewai_patch.CrewAIPatch(TerminalPendingInterceptor())
    assert patcher.apply() is True

    tool = FakeBaseTool()
    result = tool.run(param="value")

    assert isinstance(result, str)
    assert result.startswith("[APPROVAL REJECTED]")
    # The original tool never executed, so its output was never recorded. This
    # used to read `recorded_results == []`, which said the same thing only for
    # as long as the deny branch recorded nothing at all; since AAASM-5787 it
    # records the rejection, so the assertion is now about *what* was recorded.
    assert recorded_results == ["[APPROVAL REJECTED] Action was reviewed and denied: still pending"]
    assert not any(isinstance(entry, dict) for entry in recorded_results)


def test_task_start_and_complete_events_are_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, FakeTask = _install_fake_crewai_modules(monkeypatch)
    recorded: list[dict[str, object]] = []

    class TaskRecordInterceptor:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "allow"}

        def record(self, **kwargs: object) -> None:
            recorded.append(dict(kwargs))

    patcher = crewai_patch.CrewAIPatch(TaskRecordInterceptor())
    assert patcher.apply() is True

    task = FakeTask()
    result = task.execute_sync(input_text="hello")

    assert result == {"args": (), "kwargs": {"input_text": "hello"}}
    assert len(recorded) == 2
    assert recorded[0]["action"] == "task_start"
    assert recorded[1]["action"] == "task_complete"


def test_thread_local_agent_id_isolated_across_concurrent_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeBaseTool:
        name = "thread_tool"

        def run(self, *args: Any, **kwargs: Any) -> dict[str, object]:
            return {"args": args, "kwargs": kwargs}

    class FakeTask:
        description = "thread task"
        expected_output = "thread output"

        def execute_sync(self, *args: Any, **kwargs: Any) -> object:
            tool = kwargs["tool"]
            return tool.run()

    fake_crewai_tools = SimpleNamespace(BaseTool=FakeBaseTool)
    fake_crewai_module = SimpleNamespace(Task=FakeTask)

    def fake_import_module(module_name: str) -> object:
        if module_name == "crewai.tools":
            return fake_crewai_tools
        if module_name == "crewai":
            return fake_crewai_module
        raise ImportError(module_name)

    monkeypatch.setattr(crewai_patch.importlib, "import_module", fake_import_module)

    observed_agent_ids: list[str | None] = []

    class ConcurrencyInterceptor:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            observed_agent_ids.append(str(kwargs.get("agent_id")) if kwargs.get("agent_id") is not None else None)
            return {"status": "allow"}

    patcher = crewai_patch.CrewAIPatch(ConcurrencyInterceptor())
    assert patcher.apply() is True

    task = FakeTask()
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(task.execute_sync, tool=FakeBaseTool(), agent_id="agent-A")
        future_b = pool.submit(task.execute_sync, tool=FakeBaseTool(), agent_id="agent-B")
        assert future_a.result() == {"args": (), "kwargs": {}}
        assert future_b.result() == {"args": (), "kwargs": {}}

    assert sorted(observed_agent_ids) == ["agent-A", "agent-B"]  # type: ignore[type-var]  # data is str | None statically but never None here
