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

        # AAASM-4434: mypy cannot infer CompiledStateGraph's StateT generic
        # parameter from `StateGraph(_CounterState)` (a runtime-value constructor
        # argument, not a `StateGraph[_CounterState]` type-subscript), so the
        # concrete TypedDict input doesn't structurally match the generic overload
        # even though it's exactly what LangGraph expects and returns at runtime.
        result = compiled.invoke(_CounterState(count=0))  # type: ignore[arg-type]

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

        # AAASM-4434: see the matching type: ignore note on the sync test above.
        result = asyncio.run(compiled.ainvoke(_CounterState(count=0)))  # type: ignore[arg-type]

        assert result == {"count": 11}
        assert recorder.events == [
            ("start", "a"),
            ("end", "a"),
            ("start", "b"),
            ("end", "b"),
        ]
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
