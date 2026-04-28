from __future__ import annotations

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
