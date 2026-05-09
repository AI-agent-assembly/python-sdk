from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_assembly.adapters.openai_agents.patch import (
    _apply_handoff_call_patch,
    _apply_runner_run_patch,
    _extract_handoff_delegation_reason,
    _load_openai_agents_handoff_class,
    _load_openai_agents_runner_class,
    _revert_handoff_call_patch,
    _revert_runner_run_patch,
    set_process_agent_id,
)
from agent_assembly.core.spawn import _SPAWN_CTX, SpawnContext

_RUNNER_PATCHED_FLAG = "_agent_assembly_openai_agents_runner_patched"
_ORIGINAL_RUNNER_RUN = "_agent_assembly_original_openai_agents_runner_run"
_HANDOFF_PATCHED_FLAG = "_agent_assembly_openai_agents_handoff_patched"
_ORIGINAL_HANDOFF_CALL = "_agent_assembly_original_openai_agents_handoff_call"


class TestLoadRunnerClass:
    def test_returns_none_when_openai_agents_not_installed(self):
        with patch("importlib.import_module", side_effect=ImportError):
            result = _load_openai_agents_runner_class()
        assert result is None


class FakeRunner:
    """Minimal Runner stand-in for patching tests."""

    @classmethod
    async def run(cls, agent: object, **_kwargs: object) -> str:
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
        _apply_runner_run_patch(FakeRunner, "process-agent-001")
        _revert_runner_run_patch(FakeRunner)
        assert not hasattr(FakeRunner, _RUNNER_PATCHED_FLAG)
        assert not hasattr(FakeRunner, _ORIGINAL_RUNNER_RUN)
        import asyncio as _asyncio

        result = _asyncio.run(FakeRunner.run(MagicMock(), input="x"))
        assert isinstance(result, str) and result.startswith("ran:")


class TestLoadHandoffClass:
    def test_returns_none_when_openai_agents_not_installed(self):
        with patch("importlib.import_module", side_effect=ImportError):
            result = _load_openai_agents_handoff_class()
        assert result is None


class TestExtractHandoffDelegationReason:
    def test_reads_tool_description(self):
        obj = MagicMock()
        obj.tool_description = "Transfer control to agent B"
        assert _extract_handoff_delegation_reason(obj) == "Transfer control to agent B"

    def test_falls_back_to_description(self):
        obj = MagicMock(spec=["description"])
        obj.description = "Handoff description"
        assert _extract_handoff_delegation_reason(obj) == "Handoff description"

    def test_falls_back_to_reason(self):
        obj = MagicMock(spec=["reason"])
        obj.reason = "some reason"
        assert _extract_handoff_delegation_reason(obj) == "some reason"

    def test_fallback_when_no_description_attrs(self):
        obj = MagicMock(spec=[])
        assert _extract_handoff_delegation_reason(obj) == "handoff"

    def test_fallback_when_tool_description_is_empty_string(self):
        obj = MagicMock(spec=["tool_description"])
        obj.tool_description = "   "
        assert _extract_handoff_delegation_reason(obj) == "handoff"

    def test_truncates_to_256_chars(self):
        obj = MagicMock()
        obj.tool_description = "x" * 300
        result = _extract_handoff_delegation_reason(obj)
        assert len(result) == 256


class FakeHandoff:
    """Minimal Handoff stand-in for patching tests."""

    def __init__(self, tool_description: str = "") -> None:
        self.tool_description = tool_description

    async def __call__(self, *_args: object, **_kwargs: object) -> str:
        return "handoff-result"


class TestApplyHandoffCallPatch:
    def setup_method(self) -> None:
        set_process_agent_id("process-agent-001")
        for attr in (_HANDOFF_PATCHED_FLAG, _ORIGINAL_HANDOFF_CALL):
            if hasattr(FakeHandoff, attr):
                delattr(FakeHandoff, attr)

    def teardown_method(self) -> None:
        _revert_handoff_call_patch(FakeHandoff)
        set_process_agent_id(None)
        for attr in (_HANDOFF_PATCHED_FLAG, _ORIGINAL_HANDOFF_CALL):
            if hasattr(FakeHandoff, attr):
                delattr(FakeHandoff, attr)

    @pytest.mark.asyncio
    async def test_patched_handoff_sets_spawn_ctx(self):
        captured: list[SpawnContext | None] = []

        class CapturingHandoff(FakeHandoff):
            async def __call__(self, *_args: object, **_kwargs: object) -> str:
                captured.append(_SPAWN_CTX.get())
                return "done"

        _apply_handoff_call_patch(CapturingHandoff, "process-agent-001")
        h = CapturingHandoff(tool_description="transfer to B")
        await h()

        assert len(captured) == 1
        sc = captured[0]
        assert sc is not None
        assert sc.parent_agent_id == "process-agent-001"
        assert sc.depth == 1

    @pytest.mark.asyncio
    async def test_spawned_by_tool_is_none_for_handoff(self):
        captured: list[SpawnContext | None] = []

        class CapturingHandoff(FakeHandoff):
            async def __call__(self, *_args: object, **_kwargs: object) -> str:
                captured.append(_SPAWN_CTX.get())
                return "done"

        _apply_handoff_call_patch(CapturingHandoff, "process-agent-001")
        await CapturingHandoff()()

        assert captured[0] is not None
        assert captured[0].spawned_by_tool is None

    @pytest.mark.asyncio
    async def test_delegation_reason_from_tool_description(self):
        captured: list[SpawnContext | None] = []

        class CapturingHandoff(FakeHandoff):
            async def __call__(self, *_args: object, **_kwargs: object) -> str:
                captured.append(_SPAWN_CTX.get())
                return "done"

        _apply_handoff_call_patch(CapturingHandoff, "process-agent-001")
        h = CapturingHandoff(tool_description="Transfer to agent B")
        await h()

        assert captured[0] is not None
        assert captured[0].delegation_reason == "Transfer to agent B"

    @pytest.mark.asyncio
    async def test_delegation_reason_fallback_when_no_description(self):
        captured: list[SpawnContext | None] = []

        class CapturingHandoff(FakeHandoff):
            def __init__(self) -> None:
                pass  # no tool_description

            async def __call__(self, *_args: object, **_kwargs: object) -> str:
                captured.append(_SPAWN_CTX.get())
                return "done"

        _apply_handoff_call_patch(CapturingHandoff, "process-agent-001")
        await CapturingHandoff()()

        assert captured[0] is not None
        assert captured[0].delegation_reason == "handoff"

    @pytest.mark.asyncio
    async def test_spawn_ctx_reset_after_handoff(self):
        _apply_handoff_call_patch(FakeHandoff, "process-agent-001")
        h = FakeHandoff()
        await h()
        assert _SPAWN_CTX.get() is None

    @pytest.mark.asyncio
    async def test_spawn_ctx_reset_on_exception(self):
        class FailingHandoff(FakeHandoff):
            async def __call__(self, *_args: object, **_kwargs: object) -> str:
                raise RuntimeError("handoff failed")

        _apply_handoff_call_patch(FailingHandoff, "process-agent-001")
        with pytest.raises(RuntimeError, match="handoff failed"):
            await FailingHandoff()()
        assert _SPAWN_CTX.get() is None

    def test_idempotent_apply(self):
        _apply_handoff_call_patch(FakeHandoff, "process-agent-001")
        original = getattr(FakeHandoff, _ORIGINAL_HANDOFF_CALL, None)
        _apply_handoff_call_patch(FakeHandoff, "process-agent-001")
        assert getattr(FakeHandoff, _ORIGINAL_HANDOFF_CALL, None) is original

    def test_revert_restores_original(self):
        _apply_handoff_call_patch(FakeHandoff, "process-agent-001")
        _revert_handoff_call_patch(FakeHandoff)
        assert not hasattr(FakeHandoff, _HANDOFF_PATCHED_FLAG)
        assert not hasattr(FakeHandoff, _ORIGINAL_HANDOFF_CALL)

    @pytest.mark.asyncio
    async def test_depth_increments_when_inside_existing_spawn_ctx(self):
        from agent_assembly.core.spawn import spawn_context_scope

        captured: list[SpawnContext | None] = []

        class CapturingHandoff(FakeHandoff):
            async def __call__(self, *_args: object, **_kwargs: object) -> str:
                captured.append(_SPAWN_CTX.get())
                return "done"

        _apply_handoff_call_patch(CapturingHandoff, "process-agent-001")

        outer = SpawnContext(parent_agent_id="root", depth=2)
        with spawn_context_scope(outer):
            await CapturingHandoff()()

        assert captured[0] is not None
        assert captured[0].depth == 3  # outer.depth + 1
