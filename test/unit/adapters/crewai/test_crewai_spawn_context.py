from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent_assembly.adapters.crewai.patch import (
    _CREW_KICKOFF_PATCHED_FLAG,
    _TASK_PATCHED_FLAG,
    _apply_crew_kickoff_patch,
    _apply_task_execute_sync_patch,
    _extract_crew_team_id,
    _extract_manager_agent_id,
    _extract_worker_agent_id,
    _is_hierarchical_process,
    _revert_crew_kickoff_patch,
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

    def execute_sync(self, *_args: object, **_kwargs: object) -> str:
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

    def test_team_id_extracted_from_agent_crew(self):
        captured: list[SpawnContext | None] = []

        def capturing_execute(self, *args, **kwargs):
            captured.append(_SPAWN_CTX.get())
            return "done"

        FakeTask.execute_sync = capturing_execute
        _apply_task_execute_sync_patch(FakeTask, MagicMock())
        task = FakeTask(agent_id="worker-a")
        crew = MagicMock()
        crew.id = "crew-uuid-123"
        task.agent.crew = crew
        task.execute_sync()

        assert captured[0] is not None
        assert captured[0].team_id == "crew-uuid-123"

    def test_team_id_none_when_no_crew(self):
        captured: list[SpawnContext | None] = []

        def capturing_execute(self, *args, **kwargs):
            captured.append(_SPAWN_CTX.get())
            return "done"

        FakeTask.execute_sync = capturing_execute
        _apply_task_execute_sync_patch(FakeTask, MagicMock())
        task = FakeTask(agent_id="worker-b")
        task.agent = MagicMock(spec=["id"])
        task.agent.id = "worker-b"
        task.execute_sync()

        assert captured[0] is not None
        assert captured[0].team_id is None

    def test_delegation_reason_from_task_description(self):
        captured: list[SpawnContext | None] = []

        def capturing_execute(self, *args, **kwargs):
            captured.append(_SPAWN_CTX.get())
            return "done"

        FakeTask.execute_sync = capturing_execute
        _apply_task_execute_sync_patch(FakeTask, MagicMock())
        task = FakeTask(agent_id="worker-c")
        task.description = "Analyze quarterly reports"
        task.execute_sync()

        assert captured[0] is not None
        assert captured[0].delegation_reason == "Analyze quarterly reports"

    def test_delegation_reason_truncated_to_256_chars(self):
        captured: list[SpawnContext | None] = []

        def capturing_execute(self, *args, **kwargs):
            captured.append(_SPAWN_CTX.get())
            return "done"

        FakeTask.execute_sync = capturing_execute
        _apply_task_execute_sync_patch(FakeTask, MagicMock())
        task = FakeTask(agent_id="worker-d")
        task.description = "x" * 300
        task.execute_sync()

        assert captured[0] is not None
        assert len(captured[0].delegation_reason) == 256  # type: ignore[arg-type]

    def test_delegation_reason_none_when_description_empty(self):
        captured: list[SpawnContext | None] = []

        def capturing_execute(self, *args, **kwargs):
            captured.append(_SPAWN_CTX.get())
            return "done"

        FakeTask.execute_sync = capturing_execute
        _apply_task_execute_sync_patch(FakeTask, MagicMock())
        task = FakeTask(agent_id="worker-e")
        task.description = ""
        task.execute_sync()

        assert captured[0] is not None
        assert captured[0].delegation_reason is None


class TestExtractCrewTeamId:
    def test_returns_str_of_crew_id(self):
        crew = MagicMock()
        crew.id = "abc-123"
        assert _extract_crew_team_id(crew) == "abc-123"

    def test_returns_none_when_crew_is_none(self):
        assert _extract_crew_team_id(None) is None

    def test_returns_none_when_crew_has_no_id(self):
        crew = MagicMock(spec=[])
        assert _extract_crew_team_id(crew) is None

    def test_stringifies_non_str_id(self):
        crew = MagicMock()
        crew.id = 42
        assert _extract_crew_team_id(crew) == "42"


class TestExtractManagerAgentId:
    def test_returns_manager_id(self):
        crew = MagicMock()
        crew.manager_agent.id = "manager-001"
        assert _extract_manager_agent_id(crew) == "manager-001"

    def test_returns_none_when_no_manager_agent(self):
        crew = MagicMock(spec=[])
        assert _extract_manager_agent_id(crew) is None

    def test_returns_none_when_manager_has_no_id(self):
        crew = MagicMock()
        crew.manager_agent = MagicMock(spec=[])
        assert _extract_manager_agent_id(crew) is None


class FakeCrew:
    """Minimal Crew stand-in for kickoff patching tests."""

    def __init__(self, *, hierarchical: bool = False, manager_id: str = "mgr-1", crew_id: str = "crew-1") -> None:
        self.id = crew_id
        self.manager_agent = MagicMock()
        self.manager_agent.id = manager_id
        self._hierarchical = hierarchical
        self.process = "hierarchical" if hierarchical else "sequential"

    def kickoff(self, *_args: object, **_kwargs: object) -> str:
        return "crew-result"


_FAKE_CREW_ORIGINAL_KICKOFF = FakeCrew.__dict__["kickoff"]

_ORIGINAL_CREW_KICKOFF_ATTR = "_agent_assembly_original_crewai_crew_kickoff"


class TestIsHierarchicalProcess:
    def test_returns_false_for_sequential(self):
        crew = FakeCrew(hierarchical=False)
        # _is_hierarchical_process checks crew.process == Process.hierarchical;
        # without real crewai installed it resolves Process to None → returns False
        result = _is_hierarchical_process(crew)
        assert isinstance(result, bool)

    def test_returns_false_when_crewai_not_installed(self):
        from unittest.mock import patch

        with patch("importlib.import_module", side_effect=ImportError):
            result = _is_hierarchical_process(MagicMock())
        assert result is False


class TestApplyCrewKickoffPatch:
    def setup_method(self) -> None:
        for attr in (_CREW_KICKOFF_PATCHED_FLAG, _ORIGINAL_CREW_KICKOFF_ATTR):
            if hasattr(FakeCrew, attr):
                delattr(FakeCrew, attr)
        FakeCrew.kickoff = _FAKE_CREW_ORIGINAL_KICKOFF

    def teardown_method(self) -> None:
        _revert_crew_kickoff_patch(FakeCrew)
        for attr in (_CREW_KICKOFF_PATCHED_FLAG, _ORIGINAL_CREW_KICKOFF_ATTR):
            if hasattr(FakeCrew, attr):
                delattr(FakeCrew, attr)

    def test_non_hierarchical_kickoff_bypasses_spawn_ctx(self):
        from unittest.mock import patch

        captured: list[SpawnContext | None] = []
        original = FakeCrew.kickoff

        def capturing_kickoff(self, *_args, **_kwargs):
            captured.append(_SPAWN_CTX.get())
            return "done"

        FakeCrew.kickoff = capturing_kickoff
        _apply_crew_kickoff_patch(FakeCrew)

        crew = FakeCrew(hierarchical=False)
        with patch(
            "agent_assembly.adapters.crewai.patch._is_hierarchical_process",
            return_value=False,
        ):
            crew.kickoff()

        assert captured[0] is None
        FakeCrew.kickoff = original

    def test_hierarchical_kickoff_sets_spawn_ctx(self):
        from unittest.mock import patch

        captured: list[SpawnContext | None] = []
        original = FakeCrew.kickoff

        def capturing_kickoff(self, *_args, **_kwargs):
            captured.append(_SPAWN_CTX.get())
            return "done"

        FakeCrew.kickoff = capturing_kickoff
        _apply_crew_kickoff_patch(FakeCrew)

        crew = FakeCrew(hierarchical=True, manager_id="mgr-42", crew_id="crew-99")
        with patch(
            "agent_assembly.adapters.crewai.patch._is_hierarchical_process",
            return_value=True,
        ):
            crew.kickoff()

        assert captured[0] is not None
        sc = captured[0]
        assert sc.parent_agent_id == "mgr-42"
        assert sc.team_id == "crew-99"
        assert sc.spawned_by_tool == "crewai_kickoff_hierarchical"
        assert sc.depth == 1
        FakeCrew.kickoff = original

    def test_spawn_ctx_reset_after_hierarchical_kickoff(self):
        from unittest.mock import patch

        _apply_crew_kickoff_patch(FakeCrew)
        crew = FakeCrew(hierarchical=True)
        with patch(
            "agent_assembly.adapters.crewai.patch._is_hierarchical_process",
            return_value=True,
        ):
            crew.kickoff()
        assert _SPAWN_CTX.get() is None

    def test_idempotent_apply(self):
        _apply_crew_kickoff_patch(FakeCrew)
        original = getattr(FakeCrew, _ORIGINAL_CREW_KICKOFF_ATTR, None)
        _apply_crew_kickoff_patch(FakeCrew)
        assert getattr(FakeCrew, _ORIGINAL_CREW_KICKOFF_ATTR, None) is original

    def test_revert_restores_original(self):
        _apply_crew_kickoff_patch(FakeCrew)
        _revert_crew_kickoff_patch(FakeCrew)
        assert not hasattr(FakeCrew, _CREW_KICKOFF_PATCHED_FLAG)
        assert not hasattr(FakeCrew, _ORIGINAL_CREW_KICKOFF_ATTR)
        result = FakeCrew().kickoff()
        assert result == "crew-result"
