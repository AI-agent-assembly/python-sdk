from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_assembly.adapters.langgraph.patch import (
    _extract_agent_id_from_runnable_config,
    _is_compiled_subgraph,
    _is_tool_node,
    _make_subgraph_spawn_wrapper,
    _wrap_node_map,
    _wrap_tool_node_subgraphs,
)
from agent_assembly.core.spawn import _SPAWN_CTX, SpawnContext


class TestIsCompiledSubgraph:
    def test_returns_true_for_object_with_nodes_and_invoke(self) -> None:
        obj = MagicMock()
        obj.nodes = {"a": MagicMock()}
        obj.invoke = MagicMock()
        assert _is_compiled_subgraph(obj) is True

    def test_returns_false_for_callable_without_nodes(self) -> None:
        assert _is_compiled_subgraph(lambda x: x) is False

    def test_returns_false_for_object_missing_invoke(self) -> None:
        obj = MagicMock(spec=["nodes"])
        obj.nodes = {}
        assert _is_compiled_subgraph(obj) is False


class TestMakeSubgraphSpawnWrapper:
    def test_sync_wrapper_sets_spawn_ctx_then_resets(self) -> None:
        captured: list[SpawnContext | None] = []
        original_invoke = MagicMock(side_effect=lambda *_args, **_kwargs: captured.append(_SPAWN_CTX.get()) or "result")  # type: ignore[func-returns-value]
        subgraph = MagicMock()
        subgraph.invoke = original_invoke

        wrapper = _make_subgraph_spawn_wrapper(subgraph, "parent-agent")
        assert _SPAWN_CTX.get() is None

        result = wrapper({"input": "x"})

        assert result == "result"
        assert len(captured) == 1
        sc = captured[0]
        assert sc is not None
        assert sc.parent_agent_id == "parent-agent"
        assert sc.depth == 1
        assert sc.spawned_by_tool is None  # plain graph node: no tool
        assert sc.delegation_reason is None
        assert _SPAWN_CTX.get() is None

    def test_delegation_reason_passed_through(self) -> None:
        captured: list[SpawnContext | None] = []
        subgraph = MagicMock()
        subgraph.invoke = MagicMock(side_effect=lambda *_args, **_kwargs: captured.append(_SPAWN_CTX.get()) or "r")  # type: ignore[func-returns-value]

        wrapper = _make_subgraph_spawn_wrapper(
            subgraph,
            "parent",
            delegation_reason="langgraph_node:mynode",
        )
        wrapper({})

        sc = captured[0]
        assert sc is not None
        assert sc.delegation_reason == "langgraph_node:mynode"
        assert sc.spawned_by_tool is None

    def test_spawned_by_tool_passed_through_for_tool_node(self) -> None:
        captured: list[SpawnContext | None] = []
        subgraph = MagicMock()
        subgraph.invoke = MagicMock(side_effect=lambda *_args, **_kwargs: captured.append(_SPAWN_CTX.get()) or "r")  # type: ignore[func-returns-value]

        wrapper = _make_subgraph_spawn_wrapper(
            subgraph,
            "parent",
            spawned_by_tool="tool_x",
            delegation_reason="langgraph_tool:tool_x",
        )
        wrapper({})

        sc = captured[0]
        assert sc is not None
        assert sc.spawned_by_tool == "tool_x"
        assert sc.delegation_reason == "langgraph_tool:tool_x"

    @pytest.mark.asyncio
    async def test_async_wrapper_sets_spawn_ctx(self) -> None:
        captured: list[SpawnContext | None] = []

        async def fake_ainvoke(*args: object, **kwargs: object) -> str:
            captured.append(_SPAWN_CTX.get())
            return "async-result"

        subgraph = MagicMock()
        subgraph.ainvoke = fake_ainvoke
        subgraph.invoke = MagicMock()

        wrapper = _make_subgraph_spawn_wrapper(subgraph, "parent-async", async_=True)
        result = await wrapper({"input": "y"})

        assert result == "async-result"
        sc = captured[0]
        assert sc is not None
        assert sc.parent_agent_id == "parent-async"
        assert sc.depth == 1
        assert _SPAWN_CTX.get() is None

    def test_spawn_ctx_depth_increments_when_already_in_ctx(self) -> None:
        captured: list[SpawnContext | None] = []
        original_invoke = MagicMock(side_effect=lambda *_args, **_kwargs: captured.append(_SPAWN_CTX.get()) or "r")  # type: ignore[func-returns-value]
        subgraph = MagicMock()
        subgraph.invoke = original_invoke

        outer = SpawnContext(parent_agent_id="grandparent", depth=1)
        token = _SPAWN_CTX.set(outer)
        try:
            wrapper = _make_subgraph_spawn_wrapper(subgraph, "parent-agent")
            wrapper({})
        finally:
            _SPAWN_CTX.reset(token)

        sc = captured[0]
        assert sc is not None
        assert sc.depth == 2

    def test_wrapper_is_pass_through_on_exception(self) -> None:
        subgraph = MagicMock()
        subgraph.invoke = MagicMock(side_effect=RuntimeError("graph error"))

        wrapper = _make_subgraph_spawn_wrapper(subgraph, "parent")
        with pytest.raises(RuntimeError, match="graph error"):
            wrapper({})
        # Token must still be reset
        assert _SPAWN_CTX.get() is None


class _FakeSubgraph:
    """Non-callable compiled subgraph stub — satisfies _is_compiled_subgraph check."""

    def __init__(self, *, with_ainvoke: bool = False) -> None:
        self.nodes = {"a": object()}
        self.invoke = MagicMock(return_value="r")
        if with_ainvoke:
            self.ainvoke = MagicMock()


class TestWrapNodeMapSubgraph:
    def test_wrap_node_map_wraps_compiled_subgraph_sync(self) -> None:
        """_wrap_node_map replaces a compiled subgraph node with a sync spawn wrapper."""
        subgraph = _FakeSubgraph(with_ainvoke=False)
        original_subgraph = subgraph
        node_map = {"subnode": subgraph}

        result = _wrap_node_map(node_map, callback_handler=MagicMock(), process_agent_id="p-001")

        assert result is True
        assert node_map["subnode"] is not original_subgraph

    def test_wrap_node_map_wraps_compiled_subgraph_with_ainvoke(self) -> None:
        """_wrap_node_map patches both sync and async paths on a compiled subgraph."""
        subgraph = _FakeSubgraph(with_ainvoke=True)
        original_ainvoke = subgraph.ainvoke
        original_subgraph = subgraph
        node_map = {"subnode": subgraph}

        result = _wrap_node_map(node_map, callback_handler=MagicMock(), process_agent_id="p-001")

        assert result is True
        # sync wrapper installed in map
        assert node_map["subnode"] is not original_subgraph
        # async wrapper patched onto subgraph object
        assert getattr(subgraph, "_agent_assembly_ainvoke_spawned", False) is True
        assert subgraph.ainvoke is not original_ainvoke


class TestExtractAgentIdFromRunnableConfig:
    def test_reads_aaasm_agent_id_from_configurable(self) -> None:
        config = {"configurable": {"aaasm_agent_id": "parent-123"}}
        assert _extract_agent_id_from_runnable_config(config) == "parent-123"

    def test_returns_none_when_key_absent(self) -> None:
        config = {"configurable": {"other_key": "value"}}
        assert _extract_agent_id_from_runnable_config(config) is None

    def test_returns_none_for_empty_string(self) -> None:
        config = {"configurable": {"aaasm_agent_id": ""}}
        assert _extract_agent_id_from_runnable_config(config) is None

    def test_returns_none_when_configurable_missing(self) -> None:
        config = {"metadata": {"aaasm_agent_id": "parent-xyz"}}
        assert _extract_agent_id_from_runnable_config(config) is None

    def test_returns_none_for_non_dict_config(self) -> None:
        assert _extract_agent_id_from_runnable_config(None) is None
        assert _extract_agent_id_from_runnable_config("string") is None


class TestIsToolNode:
    def test_detects_tool_node_by_duck_typing(self) -> None:
        fake_tool_node = MagicMock(spec=["tools_by_name"])
        fake_tool_node.tools_by_name = {"tool_a": MagicMock()}
        assert _is_tool_node(fake_tool_node) is True

    def test_returns_false_for_compiled_subgraph(self) -> None:
        subgraph = _FakeSubgraph()
        assert _is_tool_node(subgraph) is False

    def test_returns_false_for_plain_callable(self) -> None:
        assert _is_tool_node(lambda x: x) is False

    def test_returns_false_when_tools_by_name_not_dict(self) -> None:
        obj = MagicMock()
        obj.tools_by_name = "not-a-dict"
        assert _is_tool_node(obj) is False


class TestWrapToolNodeSubgraphs:
    def test_wraps_compiled_subgraph_tool_inside_tool_node(self) -> None:
        subgraph = _FakeSubgraph()
        tool = MagicMock()
        tool.func = subgraph

        tool_node = MagicMock(spec=["tools_by_name"])
        tool_node.tools_by_name = {"search": tool}

        result = _wrap_tool_node_subgraphs(tool_node, "parent-agent")

        assert result is True
        assert tool.func is not subgraph

    def test_returns_false_when_no_compiled_subgraph_tools(self) -> None:
        plain_func = lambda x: x  # noqa: E731 — real function, not a compiled subgraph

        tool = MagicMock()
        tool.func = plain_func  # not a compiled subgraph

        tool_node = MagicMock(spec=["tools_by_name"])
        tool_node.tools_by_name = {"search": tool}

        result = _wrap_tool_node_subgraphs(tool_node, "parent-agent")

        assert result is False

    def test_spawned_by_tool_and_delegation_reason_set_for_tool_node_path(self) -> None:
        captured: list[SpawnContext | None] = []
        subgraph = _FakeSubgraph()
        subgraph.invoke = MagicMock(side_effect=lambda *_args, **_kwargs: captured.append(_SPAWN_CTX.get()) or "r")  # type: ignore[func-returns-value]

        tool = MagicMock()
        tool.func = subgraph

        tool_node = MagicMock(spec=["tools_by_name"])
        tool_node.tools_by_name = {"retriever": tool}

        _wrap_tool_node_subgraphs(tool_node, "parent-agent")

        # Invoke the wrapped function to verify spawn context values
        tool.func({})
        assert captured[0] is not None
        assert captured[0].spawned_by_tool == "retriever"
        assert captured[0].delegation_reason == "langgraph_tool:retriever"


class TestWrapNodeMapDelegationReason:
    def test_plain_subgraph_node_sets_delegation_reason(self) -> None:
        captured: list[SpawnContext | None] = []
        subgraph = _FakeSubgraph()
        subgraph.invoke = MagicMock(side_effect=lambda *_args, **_kwargs: captured.append(_SPAWN_CTX.get()) or "r")  # type: ignore[func-returns-value]
        # _wrap_node_map replaces the value in place with a callable wrapper.
        node_map: dict[str, Any] = {"my_subgraph": subgraph}

        _wrap_node_map(node_map, callback_handler=MagicMock(), process_agent_id="p")
        node_map["my_subgraph"]({})

        sc = captured[0]
        assert sc is not None
        assert sc.spawned_by_tool is None
        assert sc.delegation_reason == "langgraph_node:my_subgraph"

    def test_tool_node_in_map_triggers_tool_node_handling(self) -> None:
        subgraph = _FakeSubgraph()
        tool = MagicMock()
        tool.func = subgraph

        fake_tool_node = MagicMock(spec=["tools_by_name"])
        fake_tool_node.tools_by_name = {"search": tool}

        node_map = {"tools": fake_tool_node}
        result = _wrap_node_map(node_map, callback_handler=MagicMock(), process_agent_id="p")

        assert result is True
        assert tool.func is not subgraph
