from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from agent_assembly.adapters.pydantic_ai.patch import (
    _apply_agent_run_patch,
    _load_pydantic_ai_agent_class,
    _revert_agent_run_patch,
    set_process_agent_id,
)
from agent_assembly.core.spawn import _SPAWN_CTX, SpawnContext


_AGENT_PATCHED_FLAG = "_agent_assembly_pydantic_ai_agent_patched"
_ORIGINAL_AGENT_RUN = "_agent_assembly_original_pydantic_ai_agent_run"
_ORIGINAL_AGENT_RUN_SYNC = "_agent_assembly_original_pydantic_ai_agent_run_sync"

_FAKE_AGENT_ORIGINAL_RUN = None
_FAKE_AGENT_ORIGINAL_RUN_SYNC = None


class FakeAgent:
    model = "fake-model"

    async def run(self, *args, **kwargs):
        return "agent-result"

    def run_sync(self, *args, **kwargs):
        return "sync-result"


# Capture originals at module level for reliable teardown
_FAKE_AGENT_ORIGINAL_RUN = FakeAgent.__dict__["run"]
_FAKE_AGENT_ORIGINAL_RUN_SYNC = FakeAgent.__dict__["run_sync"]


class TestLoadPydanticAiAgentClass:
    def test_returns_none_when_not_installed(self):
        with patch("importlib.import_module", side_effect=ImportError):
            assert _load_pydantic_ai_agent_class() is None


class TestApplyAgentRunPatch:
    def setup_method(self):
        set_process_agent_id("pydantic-parent")
        FakeAgent.run = _FAKE_AGENT_ORIGINAL_RUN
        FakeAgent.run_sync = _FAKE_AGENT_ORIGINAL_RUN_SYNC
        for attr in (_AGENT_PATCHED_FLAG, _ORIGINAL_AGENT_RUN, _ORIGINAL_AGENT_RUN_SYNC):
            if hasattr(FakeAgent, attr):
                delattr(FakeAgent, attr)

    def teardown_method(self):
        _revert_agent_run_patch(FakeAgent)
        set_process_agent_id(None)
        FakeAgent.run = _FAKE_AGENT_ORIGINAL_RUN
        FakeAgent.run_sync = _FAKE_AGENT_ORIGINAL_RUN_SYNC
        for attr in (_AGENT_PATCHED_FLAG, _ORIGINAL_AGENT_RUN, _ORIGINAL_AGENT_RUN_SYNC):
            if hasattr(FakeAgent, attr):
                delattr(FakeAgent, attr)

    @pytest.mark.asyncio
    async def test_async_run_sets_spawn_ctx(self):
        captured: list[SpawnContext | None] = []

        async def capturing_run(self, *args, **kwargs):
            captured.append(_SPAWN_CTX.get())
            return "ok"

        FakeAgent.run = capturing_run
        _apply_agent_run_patch(FakeAgent, "pydantic-parent")

        agent = FakeAgent()
        await agent.run("hello")

        assert captured[0] is not None
        assert captured[0].parent_agent_id == "pydantic-parent"
        assert captured[0].depth == 1
        assert captured[0].spawned_by_tool == "pydantic_ai_agent"

    def test_sync_run_sets_spawn_ctx(self):
        captured: list[SpawnContext | None] = []

        def capturing_run_sync(self, *args, **kwargs):
            captured.append(_SPAWN_CTX.get())
            return "sync-ok"

        FakeAgent.run_sync = capturing_run_sync
        _apply_agent_run_patch(FakeAgent, "pydantic-parent")

        agent = FakeAgent()
        agent.run_sync("hello")

        assert captured[0] is not None
        assert captured[0].parent_agent_id == "pydantic-parent"

    @pytest.mark.asyncio
    async def test_spawn_ctx_reset_after_async_run(self):
        _apply_agent_run_patch(FakeAgent, "pydantic-parent")
        agent = FakeAgent()
        await agent.run("x")
        assert _SPAWN_CTX.get() is None

    def test_spawn_ctx_reset_after_sync_run(self):
        _apply_agent_run_patch(FakeAgent, "pydantic-parent")
        agent = FakeAgent()
        agent.run_sync("x")
        assert _SPAWN_CTX.get() is None

    @pytest.mark.asyncio
    async def test_spawn_ctx_reset_on_exception_async(self):
        async def failing_run(self, *args, **kwargs):
            raise RuntimeError("agent error")

        FakeAgent.run = failing_run
        _apply_agent_run_patch(FakeAgent, "pydantic-parent")

        with pytest.raises(RuntimeError):
            await FakeAgent().run("x")
        assert _SPAWN_CTX.get() is None

    def test_idempotent_apply(self):
        _apply_agent_run_patch(FakeAgent, "pydantic-parent")
        first_original = getattr(FakeAgent, _ORIGINAL_AGENT_RUN, None)
        _apply_agent_run_patch(FakeAgent, "pydantic-parent")
        assert getattr(FakeAgent, _ORIGINAL_AGENT_RUN, None) is first_original

    def test_revert_restores_original(self):
        _apply_agent_run_patch(FakeAgent, "pydantic-parent")
        _revert_agent_run_patch(FakeAgent)
        assert not hasattr(FakeAgent, _AGENT_PATCHED_FLAG)
        assert not hasattr(FakeAgent, _ORIGINAL_AGENT_RUN)
        assert not hasattr(FakeAgent, _ORIGINAL_AGENT_RUN_SYNC)
        # Verify functional restoration
        import asyncio as _asyncio
        result = _asyncio.get_event_loop().run_until_complete(FakeAgent().run("x"))
        assert result == "agent-result"
        assert FakeAgent().run_sync("x") == "sync-result"
