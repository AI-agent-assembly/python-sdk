"""Cross-framework spawn lineage integration tests.

These tests exercise the full flow:
  framework spawn adapter sets _SPAWN_CTX
  → child calls init_assembly()
  → GatewayClient is constructed with correct lineage fields

No real framework (langgraph, crewai, etc.) is required — each test simulates
what a framework adapter's patch does (set _SPAWN_CTX in scope, call a callback
that calls init_assembly()).  GatewayClient is mocked to capture the call args.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_assembly.core.assembly import init_assembly
from agent_assembly.core.spawn import _SPAWN_CTX, SpawnContext, spawn_context_scope

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GW_URL = "http://localhost:8080"
_API_KEY = "test-key"


def _call_init_assembly(**kwargs: object) -> MagicMock:
    """Call init_assembly with GatewayClient mocked; return the mock instance."""
    with patch("agent_assembly.core.assembly.GatewayClient") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.register_agent = MagicMock(return_value=None)
        mock_instance.close = MagicMock(return_value=None)
        mock_instance.gateway_url = _GW_URL.rstrip("/")
        mock_instance.agent_id = kwargs.get("agent_id", "agent-assembly-default")
        mock_instance.api_key = _API_KEY
        mock_cls.return_value = mock_instance

        # Also patch out adapter registration and network layer — we only care
        # about what GatewayClient receives.
        with (
            patch("agent_assembly.core.assembly._register_adapters", return_value=[]),
            patch(
                "agent_assembly.core.assembly._start_network_layer",
                return_value=("sdk-only", lambda: None),
            ),
            patch("agent_assembly.core.assembly._ACTIVE_CONTEXT", None),
        ):
            ctx = init_assembly(
                gateway_url=_GW_URL,
                api_key=_API_KEY,
                **kwargs,  # type: ignore[arg-type]
            )
            ctx.shutdown()

        # Return the mock so callers can inspect keyword args
        return mock_cls


# ---------------------------------------------------------------------------
# Test 1: spawn context propagates to init_assembly via GatewayClient ctor
# ---------------------------------------------------------------------------


def test_spawn_ctx_propagates_to_init_assembly() -> None:
    """SpawnContext values are forwarded to GatewayClient when set in _SPAWN_CTX."""
    spawn_ctx = SpawnContext(
        parent_agent_id="parent-001",
        depth=1,
        spawned_by_tool="test_tool",
    )

    with spawn_context_scope(spawn_ctx):
        mock_cls = _call_init_assembly(agent_id="child-001")

    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs.get("parent_agent_id") == "parent-001"
    assert call_kwargs.get("depth") == 1
    assert call_kwargs.get("spawned_by_tool") == "test_tool"


# ---------------------------------------------------------------------------
# Test 2: explicit params override spawn context
# ---------------------------------------------------------------------------


def test_explicit_params_override_spawn_ctx() -> None:
    """Explicit parent_agent_id / depth args take precedence over _SPAWN_CTX."""
    spawn_ctx = SpawnContext(
        parent_agent_id="from-ctx",
        depth=2,
        spawned_by_tool="ctx_tool",
    )

    with spawn_context_scope(spawn_ctx):
        mock_cls = _call_init_assembly(
            agent_id="child-002",
            parent_agent_id="explicit-parent",
            depth=5,
        )

    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs.get("parent_agent_id") == "explicit-parent"
    assert call_kwargs.get("depth") == 5
    # spawned_by_tool was NOT overridden — falls through from ctx
    assert call_kwargs.get("spawned_by_tool") == "ctx_tool"


# ---------------------------------------------------------------------------
# Test 3: no spawn context — explicit params used as-is
# ---------------------------------------------------------------------------


def test_no_spawn_ctx_uses_explicit_params_only() -> None:
    """When _SPAWN_CTX is not set, only explicitly passed params reach GatewayClient."""
    assert _SPAWN_CTX.get() is None  # ensure no ambient context

    mock_cls = _call_init_assembly(
        agent_id="solo-001",
        parent_agent_id="explicit-only",
        depth=3,
    )

    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs.get("parent_agent_id") == "explicit-only"
    assert call_kwargs.get("depth") == 3


# ---------------------------------------------------------------------------
# Test 4: _SPAWN_CTX resets after spawn_context_scope exits
# ---------------------------------------------------------------------------


def test_ctx_resets_after_scope_exits() -> None:
    """_SPAWN_CTX is None outside the spawn_context_scope block."""
    ctx = SpawnContext(parent_agent_id="root", depth=0, spawned_by_tool=None)

    with spawn_context_scope(ctx):
        assert _SPAWN_CTX.get() is not None

    assert _SPAWN_CTX.get() is None


# ---------------------------------------------------------------------------
# Test 5: nested scopes propagate depth correctly and restore outer scope
# ---------------------------------------------------------------------------


def test_nested_scopes_propagate_depth() -> None:
    """Inner spawn_context_scope overrides outer; outer is restored on inner exit."""
    outer_ctx = SpawnContext(parent_agent_id="root", depth=1, spawned_by_tool="outer")
    inner_ctx = SpawnContext(parent_agent_id="child", depth=2, spawned_by_tool="inner")

    with spawn_context_scope(outer_ctx):
        assert _SPAWN_CTX.get() is not None
        assert _SPAWN_CTX.get().depth == 1  # type: ignore[union-attr]

        with spawn_context_scope(inner_ctx):
            assert _SPAWN_CTX.get() is not None
            assert _SPAWN_CTX.get().depth == 2  # type: ignore[union-attr]

        # inner exited — should be back to outer
        assert _SPAWN_CTX.get() is not None
        assert _SPAWN_CTX.get().depth == 1  # type: ignore[union-attr]

    # outer exited — should be None
    assert _SPAWN_CTX.get() is None


# ---------------------------------------------------------------------------
# Test 6: exception inside scope still resets _SPAWN_CTX
# ---------------------------------------------------------------------------


def test_exception_in_scope_still_resets_ctx() -> None:
    """_SPAWN_CTX is reset even when an exception is raised inside the scope."""
    ctx = SpawnContext(parent_agent_id="root", depth=0, spawned_by_tool=None)

    with pytest.raises(RuntimeError, match="intentional"), spawn_context_scope(ctx):
        assert _SPAWN_CTX.get() is not None
        raise RuntimeError("intentional")

    assert _SPAWN_CTX.get() is None


# ---------------------------------------------------------------------------
# Test 7: chained A→B→C handoffs — depth 1→2→3, parent_agent_id correct
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chained_handoff_abc_depth_and_parent_agent_id() -> None:
    """Chained A→B→C handoffs: depth increments 1→2→3; spawned_by_tool is None."""
    from agent_assembly.adapters.openai_agents.patch import (
        _apply_handoff_call_patch,
        _revert_handoff_call_patch,
    )

    captured: list[SpawnContext] = []

    class FakeHandoff:
        def __init__(self, tool_description: str = "") -> None:
            self.tool_description = tool_description

        async def __call__(self, *_args: object, **_kwargs: object) -> str:
            sc = _SPAWN_CTX.get()
            if sc is not None:
                captured.append(sc)
            return "result"

    _apply_handoff_call_patch(FakeHandoff, "process-agent")
    try:
        # Simulate Runner.run establishing depth=1 context for Agent A
        ctx_a = SpawnContext(
            parent_agent_id="process-agent",
            depth=1,
            spawned_by_tool="openai_agents_runner",
        )
        with spawn_context_scope(ctx_a):
            # Agent A hands off to B — patch creates depth=2 spawn context
            handoff_b = FakeHandoff(tool_description="Transfer to agent B")
            await handoff_b()

        # Simulate Runner establishing depth=2 context for Agent B
        ctx_b = SpawnContext(parent_agent_id="process-agent", depth=2, spawned_by_tool=None)
        with spawn_context_scope(ctx_b):
            # Agent B hands off to C — patch creates depth=3 spawn context
            handoff_c = FakeHandoff(tool_description="Transfer to agent C")
            await handoff_c()
    finally:
        _revert_handoff_call_patch(FakeHandoff)

    assert len(captured) == 2

    sc_b = captured[0]  # spawn context seen by B's handoff call body
    assert sc_b.depth == 2
    assert sc_b.parent_agent_id == "process-agent"
    assert sc_b.spawned_by_tool is None
    assert sc_b.delegation_reason == "Transfer to agent B"

    sc_c = captured[1]  # spawn context seen by C's handoff call body
    assert sc_c.depth == 3
    assert sc_c.parent_agent_id == "process-agent"
    assert sc_c.spawned_by_tool is None
    assert sc_c.delegation_reason == "Transfer to agent C"

    assert _SPAWN_CTX.get() is None


# ---------------------------------------------------------------------------
# Test 8: CrewAI hierarchical kickoff — team_id and spawn ctx at each task
# ---------------------------------------------------------------------------


def test_crewai_hierarchical_kickoff_sets_team_id_and_spawn_ctx() -> None:
    """Crew.kickoff with hierarchical process sets _SPAWN_CTX with team_id."""
    from unittest.mock import patch

    from agent_assembly.adapters.crewai.patch import (
        _apply_crew_kickoff_patch,
        _apply_task_execute_sync_patch,
        _revert_crew_kickoff_patch,
        _revert_task_execute_sync_patch,
    )

    captured_kickoff: list[SpawnContext] = []
    captured_tasks: list[SpawnContext] = []

    class FakeCrew:
        def __init__(self) -> None:
            self.id = "crew-team-42"
            self.manager_agent = type("Mgr", (), {"id": "manager-007"})()
            self.process = "hierarchical"

        def kickoff(self, *_args: object, **_kwargs: object) -> str:
            sc = _SPAWN_CTX.get()
            if sc is not None:
                captured_kickoff.append(sc)
            # Simulate manager delegating two tasks during hierarchical kickoff
            task1 = FakeTask(description="Summarize reports", worker_id="worker-A", crew=self)
            task2 = FakeTask(description="Write conclusions", worker_id="worker-B", crew=self)
            task1.execute_sync()
            task2.execute_sync()
            return "crew-done"

    class FakeTask:
        def __init__(self, *, description: str, worker_id: str, crew: object) -> None:
            self.description = description
            self.agent = type("Agent", (), {"id": worker_id, "crew": crew})()

        def execute_sync(self, *_args: object, **_kwargs: object) -> str:
            sc = _SPAWN_CTX.get()
            if sc is not None:
                captured_tasks.append(sc)
            return "task-done"

    _apply_crew_kickoff_patch(FakeCrew)
    _apply_task_execute_sync_patch(FakeTask, type("CB", (), {})())
    try:
        crew = FakeCrew()
        with patch(
            "agent_assembly.adapters.crewai.patch._is_hierarchical_process",
            return_value=True,
        ):
            crew.kickoff()
    finally:
        _revert_task_execute_sync_patch(FakeTask)
        _revert_crew_kickoff_patch(FakeCrew)

    # kickoff body sees the outer hierarchical spawn context
    assert len(captured_kickoff) == 1
    ks = captured_kickoff[0]
    assert ks.parent_agent_id == "manager-007"
    assert ks.team_id == "crew-team-42"
    assert ks.spawned_by_tool == "crewai_kickoff_hierarchical"
    assert ks.depth == 1

    # each delegated task sees its own spawn context (depth 2 inside the kickoff scope)
    assert len(captured_tasks) == 2
    ts1, ts2 = captured_tasks
    assert ts1.parent_agent_id == "worker-A"
    assert ts1.team_id == "crew-team-42"
    assert ts1.spawned_by_tool == "crewai_task"
    assert ts1.delegation_reason == "Summarize reports"
    assert ts1.depth == 2  # incremented from kickoff's depth=1

    assert ts2.parent_agent_id == "worker-B"
    assert ts2.delegation_reason == "Write conclusions"
    assert ts2.depth == 2

    assert _SPAWN_CTX.get() is None


# ---------------------------------------------------------------------------
# Test 9: Pydantic AI tool wrap — spawn ctx inside tool execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pydantic_ai_tool_sets_spawn_ctx() -> None:
    """patched Tool._run wraps execution in spawn_context_scope with tool lineage."""
    from agent_assembly.adapters.pydantic_ai.patch import (
        _apply_tool_run_patch,
        _revert_tool_run_patch,
    )

    captured: list[SpawnContext] = []

    class _Deps:
        assembly_agent_id = "pydantic-agent-77"

    class _Ctx:
        deps = _Deps()
        run_id = "run-42"

    class FakeTool:
        name = "web_search"

        async def _run(self, _ctx: object, _args: object, **_kw: object) -> str:
            sc = _SPAWN_CTX.get()
            if sc is not None:
                captured.append(sc)
            return "search-result"

    class _AllowHandler:
        def check_tool_start(self, **_kw: object) -> dict[str, str]:
            return {"status": "allow"}

    original_run = FakeTool.__dict__["_run"]
    _apply_tool_run_patch(FakeTool, _AllowHandler())
    try:
        tool = FakeTool()
        result = await tool._run(_Ctx(), {})
    finally:
        _revert_tool_run_patch(FakeTool)
        FakeTool._run = original_run

    assert result == "search-result"
    assert len(captured) == 1
    sc = captured[0]
    assert sc.spawned_by_tool == "web_search"
    assert sc.delegation_reason == "tool:web_search"
    assert sc.parent_agent_id == "pydantic-agent-77"
    assert sc.depth == 1
    assert _SPAWN_CTX.get() is None
