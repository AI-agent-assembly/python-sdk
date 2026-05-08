from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent_assembly.adapters.langgraph.patch import (
    _is_compiled_subgraph,
    _make_subgraph_spawn_wrapper,
)
from agent_assembly.core.spawn import _SPAWN_CTX, SpawnContext


class TestIsCompiledSubgraph:
    def test_returns_true_for_object_with_nodes_and_invoke(self):
        obj = MagicMock()
        obj.nodes = {"a": MagicMock()}
        obj.invoke = MagicMock()
        assert _is_compiled_subgraph(obj) is True

    def test_returns_false_for_callable_without_nodes(self):
        assert _is_compiled_subgraph(lambda x: x) is False

    def test_returns_false_for_object_missing_invoke(self):
        obj = MagicMock(spec=["nodes"])
        obj.nodes = {}
        assert _is_compiled_subgraph(obj) is False


class TestMakeSubgraphSpawnWrapper:
    def test_sync_wrapper_sets_spawn_ctx_then_resets(self):
        captured: list[SpawnContext | None] = []
        original_invoke = MagicMock(side_effect=lambda *a, **k: captured.append(_SPAWN_CTX.get()) or "result")
        subgraph = MagicMock()
        subgraph.invoke = original_invoke

        wrapper = _make_subgraph_spawn_wrapper("subnode", subgraph, "parent-agent")
        assert _SPAWN_CTX.get() is None

        result = wrapper({"input": "x"})

        assert result == "result"
        assert len(captured) == 1
        sc = captured[0]
        assert sc is not None
        assert sc.parent_agent_id == "parent-agent"
        assert sc.depth == 1
        assert sc.spawned_by_tool == "langgraph_subgraph:subnode"
        assert _SPAWN_CTX.get() is None

    @pytest.mark.asyncio
    async def test_async_wrapper_sets_spawn_ctx(self):
        captured: list[SpawnContext | None] = []

        async def fake_ainvoke(*args, **kwargs):
            captured.append(_SPAWN_CTX.get())
            return "async-result"

        subgraph = MagicMock()
        subgraph.ainvoke = fake_ainvoke
        subgraph.invoke = MagicMock()

        wrapper = _make_subgraph_spawn_wrapper("asyncnode", subgraph, "parent-async", async_=True)
        result = await wrapper({"input": "y"})

        assert result == "async-result"
        assert captured[0].parent_agent_id == "parent-async"
        assert captured[0].depth == 1
        assert _SPAWN_CTX.get() is None

    def test_spawn_ctx_depth_increments_when_already_in_ctx(self):
        captured: list[SpawnContext | None] = []
        original_invoke = MagicMock(side_effect=lambda *a, **k: captured.append(_SPAWN_CTX.get()) or "r")
        subgraph = MagicMock()
        subgraph.invoke = original_invoke

        outer = SpawnContext(parent_agent_id="grandparent", depth=1)
        token = _SPAWN_CTX.set(outer)
        try:
            wrapper = _make_subgraph_spawn_wrapper("child", subgraph, "parent-agent")
            wrapper({})
        finally:
            _SPAWN_CTX.reset(token)

        assert captured[0].depth == 2

    def test_wrapper_is_pass_through_on_exception(self):
        subgraph = MagicMock()
        subgraph.invoke = MagicMock(side_effect=RuntimeError("graph error"))

        wrapper = _make_subgraph_spawn_wrapper("err_node", subgraph, "parent")
        with pytest.raises(RuntimeError, match="graph error"):
            wrapper({})
        # Token must still be reset
        assert _SPAWN_CTX.get() is None
