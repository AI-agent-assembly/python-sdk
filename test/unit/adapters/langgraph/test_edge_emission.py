"""Tests for LangGraph node-to-node Messages edge emission."""

from __future__ import annotations

from typing import Any

from agent_assembly.adapters.langgraph import patch as lg_patch


class RecordingEdgeEmitter:
    """Synchronous test double that records emitted edges."""

    def __init__(self) -> None:
        self.edges: list[tuple[str, str, str, dict | None]] = []

    def emit(self, source: str, target: str, edge_type: str, metadata: dict | None = None) -> None:
        self.edges.append((source, target, edge_type, metadata))


class _NullCallbackHandler:
    """Minimal callback handler that satisfies the patch interface."""

    def on_graph_node_start(self, **_kwargs: Any) -> None:
        pass

    def on_graph_node_end(self, **_kwargs: Any) -> None:
        pass


def _make_node_map(*node_names: str, handler: Any) -> dict[str, Any]:
    """Build a fake compiled-graph node map with simple callables."""
    node_map: dict[str, Any] = {}
    for name in node_names:
        def make_func(n: str) -> Any:
            def node_fn(state: Any) -> dict[str, Any]:
                return {"node": n, **state}

            return node_fn

        node_map[name] = make_func(name)
    return node_map


def _run_two_node_graph(
    node_a: str,
    node_b: str,
    emitter: RecordingEdgeEmitter,
    initial_state: dict[str, Any] | None = None,
) -> None:
    """Simulate a 2-node sequential graph execution with patched wrappers."""
    handler = _NullCallbackHandler()
    node_map = _make_node_map(node_a, node_b, handler=handler)

    lg_patch.set_edge_emitter(emitter)
    try:
        lg_patch._wrap_node_map(node_map, handler)

        state: dict[str, Any] = initial_state or {}
        state = node_map[node_a](state)
        state = node_map[node_b](state)
    finally:
        lg_patch.set_edge_emitter(None)
        lg_patch._NODE_TRANSITION.name = None


def test_messages_edge_emitted_between_two_sequential_nodes() -> None:
    emitter = RecordingEdgeEmitter()
    _run_two_node_graph("node_a", "node_b", emitter)

    assert len(emitter.edges) == 1
    src, tgt, etype, meta = emitter.edges[0]
    assert src == "node_a"
    assert tgt == "node_b"
    assert etype == "messages"
    assert isinstance(meta, dict)
    assert "transition_input_keys" in meta


def test_transition_input_keys_contains_state_keys() -> None:
    emitter = RecordingEdgeEmitter()
    _run_two_node_graph("node_a", "node_b", emitter, initial_state={"msg": "hi", "count": 0})

    assert len(emitter.edges) == 1
    meta = emitter.edges[0][3]
    assert meta is not None
    # transition_input_keys reflects the state keys seen when node_a completed
    assert set(meta["transition_input_keys"]) >= {"msg", "count"}


def test_no_edge_emitted_for_first_node_in_graph() -> None:
    """The very first node has no predecessor so no edge should be emitted."""
    emitter = RecordingEdgeEmitter()
    lg_patch.set_edge_emitter(emitter)
    try:
        handler = _NullCallbackHandler()
        node_map = _make_node_map("only_node", handler=handler)
        lg_patch._wrap_node_map(node_map, handler)
        node_map["only_node"]({})
    finally:
        lg_patch.set_edge_emitter(None)
        lg_patch._NODE_TRANSITION.name = None

    assert emitter.edges == []


def test_three_node_graph_emits_two_edges() -> None:
    emitter = RecordingEdgeEmitter()
    lg_patch.set_edge_emitter(emitter)
    try:
        handler = _NullCallbackHandler()
        node_map = _make_node_map("a", "b", "c", handler=handler)
        lg_patch._wrap_node_map(node_map, handler)
        state: dict[str, Any] = {}
        state = node_map["a"](state)
        state = node_map["b"](state)
        node_map["c"](state)
    finally:
        lg_patch.set_edge_emitter(None)
        lg_patch._NODE_TRANSITION.name = None

    assert len(emitter.edges) == 2
    assert emitter.edges[0][:3] == ("a", "b", "messages")
    assert emitter.edges[1][:3] == ("b", "c", "messages")


def test_no_edge_emitted_when_emitter_is_none() -> None:
    """When no emitter is registered, transitions must not raise."""
    lg_patch.set_edge_emitter(None)
    try:
        handler = _NullCallbackHandler()
        node_map = _make_node_map("x", "y", handler=handler)
        lg_patch._wrap_node_map(node_map, handler)
        state: dict[str, Any] = {}
        state = node_map["x"](state)
        node_map["y"](state)  # Should not raise
    finally:
        lg_patch._NODE_TRANSITION.name = None
