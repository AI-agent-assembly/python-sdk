from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_assembly.adapters.openai_agents.patch import (
    _apply_runner_run_patch,
    _load_openai_agents_runner_class,
    _revert_runner_run_patch,
    set_process_agent_id,
)
from agent_assembly.core.spawn import _SPAWN_CTX, SpawnContext

_RUNNER_PATCHED_FLAG = "_agent_assembly_openai_agents_runner_patched"
_ORIGINAL_RUNNER_RUN = "_agent_assembly_original_openai_agents_runner_run"


class TestLoadRunnerClass:
    def test_returns_none_when_openai_agents_not_installed(self):
        with patch("importlib.import_module", side_effect=ImportError):
            result = _load_openai_agents_runner_class()
        assert result is None


class FakeRunner:
    """Minimal Runner stand-in for patching tests."""

    @classmethod
    async def run(cls, agent, *, input, **kwargs):
        return f"ran:{agent}"


_FAKE_RUNNER_ORIGINAL_RUN = FakeRunner.__dict__["run"]


class TestApplyRunnerRunPatch:
    def setup_method(self):
        set_process_agent_id("process-agent-001")
        for attr in (_RUNNER_PATCHED_FLAG, _ORIGINAL_RUNNER_RUN):
            if hasattr(FakeRunner, attr):
                delattr(FakeRunner, attr)
        # Restore to the original classmethod captured at class-definition time
        FakeRunner.run = _FAKE_RUNNER_ORIGINAL_RUN

    def teardown_method(self):
        _revert_runner_run_patch(FakeRunner)
        set_process_agent_id(None)
        for attr in (_RUNNER_PATCHED_FLAG, _ORIGINAL_RUNNER_RUN):
            if hasattr(FakeRunner, attr):
                delattr(FakeRunner, attr)

    @pytest.mark.asyncio
    async def test_patched_run_sets_spawn_ctx(self):
        captured: list[SpawnContext | None] = []

        async def capturing_run(agent, *, input, **kwargs):
            captured.append(_SPAWN_CTX.get())
            return "done"

        FakeRunner.run = classmethod(capturing_run)
        _apply_runner_run_patch(FakeRunner, "process-agent-001")

        await FakeRunner.run(MagicMock(), input="hello")

        assert len(captured) == 1
        sc = captured[0]
        assert sc is not None
        assert sc.parent_agent_id == "process-agent-001"
        assert sc.depth == 1
        assert sc.spawned_by_tool == "openai_agents_runner"

    @pytest.mark.asyncio
    async def test_spawn_ctx_is_reset_after_run(self):
        async def passthrough_run(agent, *, input, **kwargs):
            return "ok"

        FakeRunner.run = classmethod(passthrough_run)
        _apply_runner_run_patch(FakeRunner, "process-agent-001")

        await FakeRunner.run(MagicMock(), input="x")
        assert _SPAWN_CTX.get() is None

    @pytest.mark.asyncio
    async def test_spawn_ctx_reset_on_exception(self):
        async def failing_run(agent, *, input, **kwargs):
            raise RuntimeError("runner failed")

        FakeRunner.run = classmethod(failing_run)
        _apply_runner_run_patch(FakeRunner, "process-agent-001")

        with pytest.raises(RuntimeError):
            await FakeRunner.run(MagicMock(), input="x")
        assert _SPAWN_CTX.get() is None

    def test_idempotent_apply(self):
        _apply_runner_run_patch(FakeRunner, "process-agent-001")
        original_run = getattr(FakeRunner, _ORIGINAL_RUNNER_RUN, None)
        _apply_runner_run_patch(FakeRunner, "process-agent-001")
        assert getattr(FakeRunner, _ORIGINAL_RUNNER_RUN, None) is original_run

    def test_revert_restores_original(self):
        original = FakeRunner.run
        _apply_runner_run_patch(FakeRunner, "process-agent-001")
        _revert_runner_run_patch(FakeRunner)
        assert not hasattr(FakeRunner, _RUNNER_PATCHED_FLAG)
        assert not hasattr(FakeRunner, _ORIGINAL_RUNNER_RUN)
        import asyncio as _asyncio

        result = _asyncio.run(FakeRunner.run(MagicMock(), input="x"))
        assert isinstance(result, str) and result.startswith("ran:")
