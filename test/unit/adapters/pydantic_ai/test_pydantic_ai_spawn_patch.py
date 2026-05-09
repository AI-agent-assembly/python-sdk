from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from agent_assembly.adapters.pydantic_ai.patch import (
    _apply_agent_run_patch,
    _apply_tool_run_patch,
    _load_pydantic_ai_agent_class,
    _revert_agent_run_patch,
    _revert_tool_run_patch,
    set_process_agent_id,
)
from agent_assembly.core.spawn import _SPAWN_CTX, SpawnContext

_AGENT_PATCHED_FLAG = "_agent_assembly_pydantic_ai_agent_patched"
_ORIGINAL_AGENT_RUN = "_agent_assembly_original_pydantic_ai_agent_run"
_ORIGINAL_AGENT_RUN_SYNC = "_agent_assembly_original_pydantic_ai_agent_run_sync"
_TOOLS_PATCHED_FLAG = "_agent_assembly_pydantic_ai_tools_patched"
_ORIGINAL_TOOL_RUN = "_agent_assembly_original_pydantic_ai_tool_run"

_FAKE_AGENT_ORIGINAL_RUN = None
_FAKE_AGENT_ORIGINAL_RUN_SYNC = None


class FakeAgent:
    model = "fake-model"

    async def run(self, *_args: object, **_kwargs: object) -> str:
        return "agent-result"

    def run_sync(self, *_args: object, **_kwargs: object) -> str:
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

    def test_spawn_ctx_reset_on_exception_sync(self):
        def failing_run_sync(self, *args, **kwargs):
            raise RuntimeError("sync agent error")

        FakeAgent.run_sync = failing_run_sync
        _apply_agent_run_patch(FakeAgent, "pydantic-parent")

        with pytest.raises(RuntimeError):
            FakeAgent().run_sync("x")
        assert _SPAWN_CTX.get() is None

    @pytest.mark.asyncio
    async def test_nested_depth_propagation(self):
        captured: list[SpawnContext | None] = []

        async def capturing_run(self, *args, **kwargs):
            captured.append(_SPAWN_CTX.get())
            return "ok"

        FakeAgent.run = capturing_run
        _apply_agent_run_patch(FakeAgent, "process-agent")

        outer_ctx = SpawnContext(parent_agent_id="grandparent", depth=2, spawned_by_tool="outer")
        token = _SPAWN_CTX.set(outer_ctx)
        try:
            await FakeAgent().run("x")
        finally:
            _SPAWN_CTX.reset(token)

        assert captured[0] is not None
        assert captured[0].depth == 3

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
        result = asyncio.run(FakeAgent().run("x"))
        assert result == "agent-result"
        assert FakeAgent().run_sync("x") == "sync-result"


# ---------------------------------------------------------------------------
# Tool spawn-context tests
# ---------------------------------------------------------------------------


class _FakeDeps:
    assembly_agent_id = "ctx-agent-99"


class _FakeCtx:
    deps = _FakeDeps()
    run_id = "run-abc"


class _FakeAllowHandler:
    def check_tool_start(self, **_kwargs: object) -> dict[str, str]:
        return {"status": "allow"}


class _FakeDenyHandler:
    def check_tool_start(self, **_kwargs: object) -> dict[str, str]:
        return {"status": "deny", "reason": "blocked"}


_FAKE_TOOL_ORIGINAL_RUN = None


class FakeTool:
    name = "search"

    async def _run(self, _ctx: object, _args: object, **_kwargs: object) -> str:
        return "tool-result"


_FAKE_TOOL_ORIGINAL_RUN = FakeTool.__dict__["_run"]


class TestApplyToolRunPatch:
    def setup_method(self) -> None:
        FakeTool._run = _FAKE_TOOL_ORIGINAL_RUN
        for attr in (_TOOLS_PATCHED_FLAG, _ORIGINAL_TOOL_RUN):
            if hasattr(FakeTool, attr):
                delattr(FakeTool, attr)

    def teardown_method(self) -> None:
        _revert_tool_run_patch(FakeTool)
        FakeTool._run = _FAKE_TOOL_ORIGINAL_RUN
        for attr in (_TOOLS_PATCHED_FLAG, _ORIGINAL_TOOL_RUN):
            if hasattr(FakeTool, attr):
                delattr(FakeTool, attr)

    @pytest.mark.asyncio
    async def test_tool_run_sets_spawned_by_tool(self) -> None:
        captured: list[SpawnContext | None] = []

        async def capturing_run(self: object, ctx: object, args: object, **kw: object) -> str:
            captured.append(_SPAWN_CTX.get())
            return "ok"

        FakeTool._run = capturing_run
        _apply_tool_run_patch(FakeTool, _FakeAllowHandler())

        await FakeTool()._run(_FakeCtx(), {})

        assert captured[0] is not None
        assert captured[0].spawned_by_tool == "search"

    @pytest.mark.asyncio
    async def test_tool_run_sets_delegation_reason(self) -> None:
        captured: list[SpawnContext | None] = []

        async def capturing_run(self: object, ctx: object, args: object, **kw: object) -> str:
            captured.append(_SPAWN_CTX.get())
            return "ok"

        FakeTool._run = capturing_run
        _apply_tool_run_patch(FakeTool, _FakeAllowHandler())

        await FakeTool()._run(_FakeCtx(), {})

        assert captured[0] is not None
        assert captured[0].delegation_reason == "tool:search"

    @pytest.mark.asyncio
    async def test_tool_run_sets_parent_agent_id_from_ctx(self) -> None:
        captured: list[SpawnContext | None] = []

        async def capturing_run(self: object, ctx: object, args: object, **kw: object) -> str:
            captured.append(_SPAWN_CTX.get())
            return "ok"

        FakeTool._run = capturing_run
        _apply_tool_run_patch(FakeTool, _FakeAllowHandler())

        await FakeTool()._run(_FakeCtx(), {})

        assert captured[0] is not None
        assert captured[0].parent_agent_id == "ctx-agent-99"

    @pytest.mark.asyncio
    async def test_spawn_ctx_reset_after_tool_run(self) -> None:
        _apply_tool_run_patch(FakeTool, _FakeAllowHandler())
        await FakeTool()._run(_FakeCtx(), {})
        assert _SPAWN_CTX.get() is None

    @pytest.mark.asyncio
    async def test_spawn_ctx_reset_on_tool_exception(self) -> None:
        async def failing_run(self: object, ctx: object, args: object, **kw: object) -> str:
            raise RuntimeError("tool broke")

        FakeTool._run = failing_run
        _apply_tool_run_patch(FakeTool, _FakeAllowHandler())

        with pytest.raises(RuntimeError):
            await FakeTool()._run(_FakeCtx(), {})
        assert _SPAWN_CTX.get() is None

    @pytest.mark.asyncio
    async def test_denied_tool_does_not_set_spawn_ctx(self) -> None:
        called = []

        async def should_not_be_called(self: object, ctx: object, args: object, **kw: object) -> str:
            called.append(True)
            return "should-not-run"

        FakeTool._run = should_not_be_called
        _apply_tool_run_patch(FakeTool, _FakeDenyHandler())

        from agent_assembly.exceptions import PolicyViolationError

        with pytest.raises(PolicyViolationError):
            await FakeTool()._run(_FakeCtx(), {})

        assert called == []
        assert _SPAWN_CTX.get() is None

    @pytest.mark.asyncio
    async def test_tool_run_depth_increments_with_outer_ctx(self) -> None:
        captured: list[SpawnContext | None] = []

        async def capturing_run(self: object, ctx: object, args: object, **kw: object) -> str:
            captured.append(_SPAWN_CTX.get())
            return "ok"

        FakeTool._run = capturing_run
        _apply_tool_run_patch(FakeTool, _FakeAllowHandler())

        outer = SpawnContext(parent_agent_id="parent", depth=3, spawned_by_tool="outer")
        token = _SPAWN_CTX.set(outer)
        try:
            await FakeTool()._run(_FakeCtx(), {})
        finally:
            _SPAWN_CTX.reset(token)

        assert captured[0] is not None
        assert captured[0].depth == 4

    def test_idempotent_tool_run_patch(self) -> None:
        _apply_tool_run_patch(FakeTool, _FakeAllowHandler())
        first_original = getattr(FakeTool, _ORIGINAL_TOOL_RUN, None)
        _apply_tool_run_patch(FakeTool, _FakeAllowHandler())
        assert getattr(FakeTool, _ORIGINAL_TOOL_RUN, None) is first_original

    def test_revert_tool_run_patch_restores_original(self) -> None:
        _apply_tool_run_patch(FakeTool, _FakeAllowHandler())
        _revert_tool_run_patch(FakeTool)
        assert not hasattr(FakeTool, _TOOLS_PATCHED_FLAG)
        assert not hasattr(FakeTool, _ORIGINAL_TOOL_RUN)
        result = asyncio.run(FakeTool()._run(_FakeCtx(), {}))
        assert result == "tool-result"
