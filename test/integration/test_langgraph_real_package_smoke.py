"""Smoke test for the LangGraph patch against the REAL ``langgraph`` package.

AAASM-4434: every existing LangGraph adapter test (unit and "integration") drives
``agent_assembly.adapters.langgraph.patch`` against a hand-rolled
``SimpleNamespace``/``FakeStateGraph`` double whose compiled-graph node map holds
directly-callable node functions — the node-map shape LangGraph used pre-1.0. The
patch was never once exercised against a real, installed ``langgraph``, so a real
breaking API change went undetected: in current LangGraph, a compiled graph's
``.nodes`` dict holds ``PregelNode`` wrapper objects whose own ``.invoke``/
``.ainvoke`` are *not* what the Pregel runtime calls during execution — it
dispatches through the wrapped Runnable at ``PregelNode.bound`` instead. Wrapping
``PregelNode.invoke`` (what every existing mock effectively does) silently never
fires: ``patch.apply()`` returns ``True``, the graph runs and returns the correct
result, and the governance hooks are simply skipped.

This module closes that gap with a real ``StateGraph`` — compiled and invoked (not
mocked) — so a regression to the pre-fix behavior (hooks silently not firing) is
actually caught. It is guarded by ``pytest.importorskip`` so the default suite
(which does not install ``langgraph``) skips it cleanly; the ``test`` dependency
group installs ``langgraph>=1.2.9,<2`` (see AAASM-4434 in ``pyproject.toml``) so it
runs wherever the full dev/test environment is installed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import TypedDict

import pytest

langgraph = pytest.importorskip("langgraph")
from langgraph.graph import END, START  # noqa: E402
from langgraph.graph.state import StateGraph  # noqa: E402

from agent_assembly.adapters.langgraph import (  # noqa: E402
    patch as langgraph_patch_module,
)
from agent_assembly.adapters.langgraph.patch import LangGraphPatch  # noqa: E402
from agent_assembly.core.spawn import _SPAWN_CTX, SpawnContext  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_node_transition_thread_local() -> Iterator[None]:
    """Reset the module-level node-transition tracker around each test.

    ``langgraph_patch_module._NODE_TRANSITION`` is a plain module-level
    ``threading.local()`` (not test-scoped), so a node name left over from one
    test's graph execution otherwise leaks into the next test's edge-emission
    bookkeeping (see AAASM-4434 / test/unit/adapters/langgraph/test_edge_emission.py
    for the existing, same-shaped teardown reset this mirrors).
    """
    langgraph_patch_module._NODE_TRANSITION.name = None
    yield
    langgraph_patch_module._NODE_TRANSITION.name = None


class _CounterState(TypedDict):
    count: int


class _EventRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def on_graph_node_start(self, **kwargs: object) -> None:
        self.events.append(("start", str(kwargs.get("node_name"))))

    def on_graph_node_end(self, **kwargs: object) -> None:
        self.events.append(("end", str(kwargs.get("node_name"))))


def _sync_add_one(state: _CounterState) -> dict[str, int]:
    return {"count": state["count"] + 1}


def _sync_add_ten(state: _CounterState) -> dict[str, int]:
    return {"count": state["count"] + 10}


async def _async_add_one(state: _CounterState) -> dict[str, int]:
    return {"count": state["count"] + 1}


async def _async_add_ten(state: _CounterState) -> dict[str, int]:
    return {"count": state["count"] + 10}


@pytest.mark.integration
def test_real_stategraph_sync_invoke_fires_node_hooks() -> None:
    """A real compiled StateGraph must actually fire start/end hooks per node.

    Regresses the AAASM-4434 bug: wrapping ``PregelNode.invoke`` (the node-map
    value itself) instead of ``PregelNode.bound.invoke`` (the Runnable the Pregel
    engine actually calls) makes ``patch.apply()`` return ``True`` while every
    hook silently never fires.
    """
    recorder = _EventRecorder()
    patch = LangGraphPatch(callback_handler=recorder)
    assert patch.apply() is True

    try:
        graph = StateGraph(_CounterState)
        graph.add_node("a", _sync_add_one)
        graph.add_node("b", _sync_add_ten)
        graph.add_edge(START, "a")
        graph.add_edge("a", "b")
        graph.add_edge("b", END)
        compiled = graph.compile()

        result = compiled.invoke(_CounterState(count=0))

        assert result == {"count": 11}
        assert recorder.events == [
            ("start", "a"),
            ("end", "a"),
            ("start", "b"),
            ("end", "b"),
        ]
    finally:
        patch.revert()


@pytest.mark.integration
def test_real_stategraph_async_ainvoke_fires_node_hooks() -> None:
    """The async execution path (``ainvoke``) must also fire node hooks."""
    recorder = _EventRecorder()
    patch = LangGraphPatch(callback_handler=recorder)
    assert patch.apply() is True

    try:
        graph = StateGraph(_CounterState)
        graph.add_node("a", _async_add_one)
        graph.add_node("b", _async_add_ten)
        graph.add_edge(START, "a")
        graph.add_edge("a", "b")
        graph.add_edge("b", END)
        compiled = graph.compile()

        result = asyncio.run(compiled.ainvoke(_CounterState(count=0)))

        assert result == {"count": 11}
        assert recorder.events == [
            ("start", "a"),
            ("end", "a"),
            ("start", "b"),
            ("end", "b"),
        ]
    finally:
        patch.revert()


@pytest.mark.integration
def test_real_stategraph_subgraph_as_node_propagates_spawn_lineage() -> None:
    """A compiled subgraph used as a parent-graph node must get spawn lineage.

    Regresses AAASM-4472: ``_wrap_node_entry`` checked ``_is_compiled_subgraph()``
    against the *outer* ``PregelNode`` wrapper before unwrapping it via ``.bound``.
    That outer wrapper never exposes ``.nodes``, so the check failed and the code
    fell through to generic hook-wrapping instead of ``_wrap_subgraph_spawn_node``.
    Coarse hooks still fired, but ``_SPAWN_CTX`` was never set inside the
    subgraph's own nodes, so parent-agent lineage was lost for the standard
    multi-agent delegation pattern (``parent_graph.add_node("sub", compiled_subgraph)``).
    """
    captured_spawn_ctx: list[SpawnContext | None] = []

    def _inner_node(state: _CounterState) -> dict[str, int]:
        captured_spawn_ctx.append(_SPAWN_CTX.get())
        return {"count": state["count"] + 1}

    sub_graph = StateGraph(_CounterState)
    sub_graph.add_node("inner", _inner_node)
    sub_graph.add_edge(START, "inner")
    sub_graph.add_edge("inner", END)
    compiled_subgraph = sub_graph.compile()

    recorder = _EventRecorder()
    patch = LangGraphPatch(callback_handler=recorder, process_agent_id="parent-agent-42")
    assert patch.apply() is True

    try:
        parent_graph = StateGraph(_CounterState)
        parent_graph.add_node("sub", compiled_subgraph)
        parent_graph.add_edge(START, "sub")
        parent_graph.add_edge("sub", END)
        compiled_parent = parent_graph.compile()

        result = compiled_parent.invoke(_CounterState(count=0))

        assert result == {"count": 1}
        assert len(captured_spawn_ctx) == 1
        spawn_ctx = captured_spawn_ctx[0]
        assert spawn_ctx is not None, "expected _SPAWN_CTX to be populated inside the subgraph's own node"
        assert spawn_ctx.parent_agent_id == "parent-agent-42"
        assert spawn_ctx.delegation_reason == "langgraph_node:sub"
    finally:
        patch.revert()


@pytest.mark.integration
def test_real_stategraph_reused_subgraph_across_parents_sync_invoke_lineage_depth_stable() -> None:
    """A compiled subgraph reused as a node in two different parent graphs must not
    accumulate wrapping layers on ``.invoke``.

    Regresses AAASM-4474: ``_wrap_subgraph_invoke_methods_in_place`` guards the
    async path against double-wrapping via ``_agent_assembly_ainvoke_spawned``,
    but has no equivalent guard for the sync path. Compiling a second parent
    graph that reuses the same compiled subgraph instance re-wraps ``.invoke``
    around the already-wrapped ``.invoke``, so a single synchronous invoke of the
    first parent graph corrupts the lineage depth captured inside the subgraph's
    own node (comes back as 2 instead of the expected 1).
    """
    captured_depths: list[int | None] = []

    def _inner_node(state: _CounterState) -> dict[str, int]:
        spawn_ctx = _SPAWN_CTX.get()
        captured_depths.append(spawn_ctx.depth if spawn_ctx is not None else None)
        return {"count": state["count"] + 1}

    sub_graph = StateGraph(_CounterState)
    sub_graph.add_node("inner", _inner_node)
    sub_graph.add_edge(START, "inner")
    sub_graph.add_edge("inner", END)
    compiled_subgraph = sub_graph.compile()

    recorder = _EventRecorder()
    patch = LangGraphPatch(callback_handler=recorder, process_agent_id="parent-agent-a")
    assert patch.apply() is True

    try:
        parent_graph_a = StateGraph(_CounterState)
        parent_graph_a.add_node("sub", compiled_subgraph)
        parent_graph_a.add_edge(START, "sub")
        parent_graph_a.add_edge("sub", END)
        compiled_parent_a = parent_graph_a.compile()

        # Reuse the same compiled subgraph instance as a node in a second,
        # unrelated parent graph. This is a legitimate pattern (a shared
        # reusable subgraph mounted under multiple parent orchestrators) and is
        # what triggers the double-wrap when compiled a second time.
        parent_graph_b = StateGraph(_CounterState)
        parent_graph_b.add_node("sub", compiled_subgraph)
        parent_graph_b.add_edge(START, "sub")
        parent_graph_b.add_edge("sub", END)
        parent_graph_b.compile()

        result = compiled_parent_a.invoke(_CounterState(count=0))

        assert result == {"count": 1}
        assert captured_depths == [1], (
            "expected lineage depth 1 for a sync invoke of a subgraph reused "
            "across two parent graphs, not an accumulated double-wrap depth"
        )
    finally:
        patch.revert()


@pytest.mark.integration
def test_real_stategraph_reused_subgraph_across_parents_async_ainvoke_lineage_depth_stable() -> None:
    """Async counterpart of the sync test above.

    The existing ``_agent_assembly_ainvoke_spawned`` guard already prevents
    double-wrapping ``.ainvoke``, so this must already pass before the sync fix
    lands and must keep passing afterward as a regression guard confirming the
    async path stays correct.
    """
    captured_depths: list[int | None] = []

    def _inner_node(state: _CounterState) -> dict[str, int]:
        spawn_ctx = _SPAWN_CTX.get()
        captured_depths.append(spawn_ctx.depth if spawn_ctx is not None else None)
        return {"count": state["count"] + 1}

    sub_graph = StateGraph(_CounterState)
    sub_graph.add_node("inner", _inner_node)
    sub_graph.add_edge(START, "inner")
    sub_graph.add_edge("inner", END)
    compiled_subgraph = sub_graph.compile()

    recorder = _EventRecorder()
    patch = LangGraphPatch(callback_handler=recorder, process_agent_id="parent-agent-a")
    assert patch.apply() is True

    try:
        parent_graph_a = StateGraph(_CounterState)
        parent_graph_a.add_node("sub", compiled_subgraph)
        parent_graph_a.add_edge(START, "sub")
        parent_graph_a.add_edge("sub", END)
        compiled_parent_a = parent_graph_a.compile()

        parent_graph_b = StateGraph(_CounterState)
        parent_graph_b.add_node("sub", compiled_subgraph)
        parent_graph_b.add_edge(START, "sub")
        parent_graph_b.add_edge("sub", END)
        parent_graph_b.compile()

        result = asyncio.run(compiled_parent_a.ainvoke(_CounterState(count=0)))

        assert result == {"count": 1}
        assert captured_depths == [1]
    finally:
        patch.revert()


def test_revert_restores_the_real_stategraph_compile() -> None:
    """``revert()`` must restore the genuine (unpatched) ``StateGraph.compile``."""
    original_compile = StateGraph.compile
    patch = LangGraphPatch(callback_handler=_EventRecorder())

    assert patch.apply() is True
    assert StateGraph.compile is not original_compile

    patch.revert()

    assert StateGraph.compile is original_compile
