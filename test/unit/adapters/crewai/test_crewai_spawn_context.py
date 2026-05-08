from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent_assembly.adapters.crewai.patch import (
    _TASK_PATCHED_FLAG,
    _apply_task_execute_sync_patch,
    _extract_worker_agent_id,
    _revert_task_execute_sync_patch,
)
from agent_assembly.core.spawn import _SPAWN_CTX, SpawnContext


class TestExtractWorkerAgentId:
    def test_returns_agent_id_from_task_agent_id(self):
        task = MagicMock()
        task.agent.id = "worker-001"
        assert _extract_worker_agent_id(task) == "worker-001"

    def test_returns_agent_id_from_task_agent_agent_id_fallback(self):
        task = MagicMock(spec=["agent"])
        task.agent = MagicMock(spec=["agent_id"])
        task.agent.agent_id = "worker-002"
        assert _extract_worker_agent_id(task) == "worker-002"

    def test_returns_none_when_no_agent(self):
        task = MagicMock(spec=[])
        assert _extract_worker_agent_id(task) is None

    def test_returns_none_when_agent_has_no_id_attrs(self):
        task = MagicMock(spec=["agent"])
        task.agent = MagicMock(spec=[])
        assert _extract_worker_agent_id(task) is None


class FakeTask:
    def __init__(self, agent_id: str | None = "worker-x"):
        self.description = "do something"
        self.expected_output = "result"
        if agent_id is not None:
            agent = MagicMock()
            agent.id = agent_id
            self.agent = agent
        else:
            self.agent = MagicMock(spec=[])

    def execute_sync(self, *args, **kwargs):
        return "task-done"


class TestTaskExecuteSyncSpawnContext:
    def setup_method(self):
        for attr in (_TASK_PATCHED_FLAG, "_agent_assembly_original_crewai_task_execute_sync"):
            if hasattr(FakeTask, attr):
                delattr(FakeTask, attr)

    def teardown_method(self):
        _revert_task_execute_sync_patch(FakeTask)

    def test_spawn_ctx_set_during_execute_sync(self):
        captured: list[SpawnContext | None] = []

        def capturing_execute(self, *args, **kwargs):
            captured.append(_SPAWN_CTX.get())
            return "done"

        FakeTask.execute_sync = capturing_execute
        _apply_task_execute_sync_patch(FakeTask, MagicMock())
        task = FakeTask(agent_id="worker-x")
        task.execute_sync()

        assert captured[0] is not None
        assert captured[0].parent_agent_id == "worker-x"
        assert captured[0].spawned_by_tool == "crewai_task"

    def test_spawn_ctx_reset_after_execute_sync(self):
        _apply_task_execute_sync_patch(FakeTask, MagicMock())
        task = FakeTask(agent_id="worker-y")
        task.execute_sync()
        assert _SPAWN_CTX.get() is None

    def test_spawn_ctx_reset_on_exception(self):
        def failing_execute(self, *args, **kwargs):
            raise RuntimeError("task failed")

        FakeTask.execute_sync = failing_execute
        _apply_task_execute_sync_patch(FakeTask, MagicMock())
        task = FakeTask(agent_id="worker-z")

        with pytest.raises(RuntimeError):
            task.execute_sync()
        assert _SPAWN_CTX.get() is None

    def test_no_spawn_ctx_when_no_agent_id(self):
        captured: list[SpawnContext | None] = []

        def capturing_execute(self, *args, **kwargs):
            captured.append(_SPAWN_CTX.get())
            return "done"

        FakeTask.execute_sync = capturing_execute
        _apply_task_execute_sync_patch(FakeTask, MagicMock())
        task = FakeTask(agent_id=None)
        task.execute_sync()

        assert captured[0] is None
