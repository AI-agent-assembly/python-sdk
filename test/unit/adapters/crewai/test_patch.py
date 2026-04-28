from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters.crewai import patch as crewai_patch


class _RecordingInterceptor:
    def check_tool_start(self, **kwargs: object) -> dict[str, str]:
        del kwargs
        return {"status": "allow"}


def _install_fake_crewai_modules(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_apply_patches_crewai_run_and_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_crewai_modules(monkeypatch)

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

    patcher = crewai_patch.CrewAIPatch(_RecordingInterceptor())
    assert patcher.apply() is True
    first_run_ref = FakeBaseTool.run
    first_task_ref = FakeTask.execute_sync

    assert getattr(FakeBaseTool, crewai_patch._TOOLS_PATCHED_FLAG, False) is True
    assert getattr(FakeTask, crewai_patch._TASK_PATCHED_FLAG, False) is True

    assert patcher.apply() is True
    assert FakeBaseTool.run is first_run_ref
    assert FakeTask.execute_sync is first_task_ref
