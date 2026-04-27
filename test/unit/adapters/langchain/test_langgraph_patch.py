from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters.langchain import langgraph_patch


class _TestAwaitable:
    def __await__(self):  # type: ignore[no-untyped-def]
        if False:
            yield None
        return None


class GraphEventRecorder:
    def __init__(self, await_callbacks: bool = False) -> None:
        self.await_callbacks = await_callbacks
        self.events: list[tuple[str, str, object]] = []

    def on_graph_node_start(self, *, node_name: str, state: object) -> object:
        self.events.append(("start", node_name, state))
        if self.await_callbacks:
            return _TestAwaitable()
        return None

    def on_graph_node_end(self, *, node_name: str, state: object, result: object) -> object:
        self.events.append(("end", node_name, result))
        if self.await_callbacks:
            return _TestAwaitable()
        return None


def test_extract_state_prefers_args_and_falls_back_to_kwargs() -> None:
    assert langgraph_patch._extract_state(({"from": "args"},), {"state": {"from": "kwargs"}}) == {
        "from": "args"
    }
    assert langgraph_patch._extract_state((), {"state": {"from": "kwargs"}}) == {
        "from": "kwargs"
    }


def test_invoke_hooks_handle_missing_methods_and_awaitables() -> None:
    # Missing hook methods should no-op.
    langgraph_patch._invoke_pre_node_hook(object(), "n1", {"state": 1})
    langgraph_patch._invoke_post_node_hook(object(), "n1", {"state": 1}, {"result": 1})

    recorder = GraphEventRecorder(await_callbacks=True)
    langgraph_patch._invoke_pre_node_hook(recorder, "n2", {"state": 2})
    langgraph_patch._invoke_post_node_hook(recorder, "n2", {"state": 2}, {"result": 2})

    assert recorder.events == [
        ("start", "n2", {"state": 2}),
        ("end", "n2", {"result": 2}),
    ]


@pytest.mark.asyncio
async def test_wrap_node_callable_handles_already_wrapped_and_async_results() -> None:
    recorder = GraphEventRecorder()

    async def async_node(state: dict[str, object]) -> dict[str, object]:
        return {"ok": state}

    wrapped_async = langgraph_patch._wrap_node_callable("async_node", async_node, recorder)
    async_result = wrapped_async({"v": 1})
    assert async_result is not None
    assert await async_result == {"ok": {"v": 1}}

    def already_wrapped(state: dict[str, object]) -> dict[str, object]:
        return {"state": state}

    setattr(already_wrapped, langgraph_patch._NODE_WRAPPED_FLAG, True)
    assert langgraph_patch._wrap_node_callable("wrapped", already_wrapped, recorder) is already_wrapped

    assert recorder.events == [
        ("start", "async_node", {"v": 1}),
        ("end", "async_node", {"ok": {"v": 1}}),
    ]


def test_wrap_node_map_covers_non_mapping_and_assignment_failure() -> None:
    assert langgraph_patch._wrap_node_map(object(), GraphEventRecorder()) is False

    class FailingNodeMap:
        def __init__(self) -> None:
            self._items = {"node": lambda state: state}

        def items(self) -> Any:
            return self._items.items()

        def __setitem__(self, key: object, value: object) -> None:
            del key, value
            raise RuntimeError("cannot assign")

    assert langgraph_patch._wrap_node_map(FailingNodeMap(), GraphEventRecorder()) is False


@pytest.mark.asyncio
async def test_wrap_node_map_wraps_invoke_and_ainvoke_members() -> None:
    recorder = GraphEventRecorder()

    class InvokeNode:
        def invoke(self, state: dict[str, object]) -> dict[str, object]:
            return {"invoke": state}

        async def ainvoke(self, state: dict[str, object]) -> dict[str, object]:
            return {"ainvoke": state}

    node = InvokeNode()
    node_map: dict[str, object] = {"node": node}
    assert langgraph_patch._wrap_node_map(node_map, recorder) is True

    invoke_result = node.invoke({"v": 1})
    ainvoke_result = await node.ainvoke({"v": 2})

    assert invoke_result == {"invoke": {"v": 1}}
    assert ainvoke_result == {"ainvoke": {"v": 2}}
    assert recorder.events == [
        ("start", "node", {"v": 1}),
        ("end", "node", {"invoke": {"v": 1}}),
        ("start", "node", {"v": 2}),
        ("end", "node", {"ainvoke": {"v": 2}}),
    ]


def test_wrap_compiled_graph_nodes_supports_pregel_fallback() -> None:
    recorder = GraphEventRecorder()

    class FakeCompiledGraph:
        def __init__(self) -> None:
            self.nodes = None
            self._nodes = None
            self.pregel = None
            self._pregel = SimpleNamespace(
                nodes={"pregel_node": lambda state: {"pregel": state}},
                _nodes=None,
            )

    compiled_graph = FakeCompiledGraph()
    assert langgraph_patch._wrap_compiled_graph_nodes(compiled_graph, recorder) is True

    result = compiled_graph._pregel.nodes["pregel_node"]({"k": 1})
    assert result == {"pregel": {"k": 1}}
    assert recorder.events == [
        ("start", "pregel_node", {"k": 1}),
        ("end", "pregel_node", {"pregel": {"k": 1}}),
    ]


def test_patch_stategraph_compile_handles_import_and_stategraph_edge_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agent_assembly.adapters.langchain.langgraph_patch.importlib.import_module",
        lambda name: (_ for _ in ()).throw(ImportError(name)),
    )
    assert langgraph_patch.patch_stategraph_compile(GraphEventRecorder()) is False

    monkeypatch.setattr(
        "agent_assembly.adapters.langchain.langgraph_patch.importlib.import_module",
        lambda name: SimpleNamespace(),
    )
    assert langgraph_patch.patch_stategraph_compile(GraphEventRecorder()) is False

    class AlreadyPatchedStateGraph:
        compile = lambda self: object()

    setattr(AlreadyPatchedStateGraph, langgraph_patch._PATCHED_FLAG, True)
    monkeypatch.setattr(
        "agent_assembly.adapters.langchain.langgraph_patch.importlib.import_module",
        lambda name: SimpleNamespace(StateGraph=AlreadyPatchedStateGraph),
    )
    assert langgraph_patch.patch_stategraph_compile(GraphEventRecorder()) is True


def test_patch_stategraph_compile_fallback_wraps_sync_invoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = GraphEventRecorder()

    class FallbackCompiledGraph:
        def invoke(self, *, state: dict[str, object]) -> dict[str, object]:
            return {"invoke": state}

    class StateGraphWithFallbackInvoke:
        def compile(self) -> FallbackCompiledGraph:
            return FallbackCompiledGraph()

    fake_module = SimpleNamespace(StateGraph=StateGraphWithFallbackInvoke)
    monkeypatch.setattr(
        "agent_assembly.adapters.langchain.langgraph_patch.importlib.import_module",
        lambda name: fake_module,
    )

    assert langgraph_patch.patch_stategraph_compile(recorder) is True
    compiled_graph = StateGraphWithFallbackInvoke().compile()
    result = compiled_graph.invoke(state={"n": 1})

    assert result == {"invoke": {"n": 1}}
    assert recorder.events == [
        ("start", "graph.invoke", {"n": 1}),
        ("end", "graph.invoke", {"invoke": {"n": 1}}),
    ]


@pytest.mark.asyncio
async def test_patch_stategraph_compile_fallback_wraps_async_invoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = GraphEventRecorder()

    class AsyncFallbackCompiledGraph:
        async def invoke(self, state: dict[str, object]) -> dict[str, object]:
            return {"invoke": state}

    class StateGraphWithAsyncFallbackInvoke:
        def compile(self) -> AsyncFallbackCompiledGraph:
            return AsyncFallbackCompiledGraph()

    fake_module = SimpleNamespace(StateGraph=StateGraphWithAsyncFallbackInvoke)
    monkeypatch.setattr(
        "agent_assembly.adapters.langchain.langgraph_patch.importlib.import_module",
        lambda name: fake_module,
    )

    assert langgraph_patch.patch_stategraph_compile(recorder) is True
    compiled_graph = StateGraphWithAsyncFallbackInvoke().compile()
    result = await compiled_graph.invoke({"n": 2})

    assert result == {"invoke": {"n": 2}}
    assert recorder.events == [
        ("start", "graph.invoke", {"n": 2}),
        ("end", "graph.invoke", {"invoke": {"n": 2}}),
    ]
