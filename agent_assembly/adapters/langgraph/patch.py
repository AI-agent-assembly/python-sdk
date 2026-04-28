"""LangGraph patch module."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Any

_PATCHED_FLAG = "_agent_assembly_compile_patched"
_ORIGINAL_COMPILE = "_agent_assembly_original_compile"


@dataclass(slots=True)
class LangGraphPatch:
    """Applies LangGraph runtime monkey-patching for node-level governance hooks."""

    callback_handler: Any

    def apply(self) -> bool:
        """Apply patching once and return whether patch wiring is active."""
        state_graph_cls = _load_stategraph_class()
        if state_graph_cls is None:
            return False
        if getattr(state_graph_cls, _PATCHED_FLAG, False):
            return True
        return True


def _extract_state(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    if args:
        return args[0]
    return kwargs.get("state")


def _extract_agent_id(config: object) -> str | None:
    if not isinstance(config, dict):
        return None

    direct_agent_id = config.get("agent_id")
    if isinstance(direct_agent_id, str) and direct_agent_id:
        return direct_agent_id

    configurable = config.get("configurable")
    if isinstance(configurable, dict):
        nested_agent_id = configurable.get("agent_id")
        if isinstance(nested_agent_id, str) and nested_agent_id:
            return nested_agent_id

    metadata = config.get("metadata")
    if isinstance(metadata, dict):
        metadata_agent_id = metadata.get("agent_id")
        if isinstance(metadata_agent_id, str) and metadata_agent_id:
            return metadata_agent_id

    return None


def _summarize_state_keys(state: object) -> list[str]:
    if not isinstance(state, dict):
        return []
    return [str(key) for key in state.keys()]


def _compute_state_delta(previous_state: object, next_state: object) -> dict[str, object]:
    if not isinstance(previous_state, dict) or not isinstance(next_state, dict):
        return {"changed_keys": [], "new_values": {}, "removed_keys": []}

    changed_keys: list[str] = []
    new_values: dict[str, object] = {}
    for key, value in next_state.items():
        if key not in previous_state or previous_state[key] != value:
            key_str = str(key)
            changed_keys.append(key_str)
            new_values[key_str] = value

    removed_keys = [str(key) for key in previous_state.keys() if key not in next_state]

    return {
        "changed_keys": changed_keys,
        "new_values": new_values,
        "removed_keys": removed_keys,
    }


def _make_sync_node_wrapper(node_name: str, original_func: Any, callback_handler: Any) -> Any:
    def wrapped_node(*node_args: Any, **node_kwargs: Any) -> Any:
        del node_name, callback_handler
        return original_func(*node_args, **node_kwargs)

    return wrapped_node


def _make_async_node_wrapper(node_name: str, original_func: Any, callback_handler: Any) -> Any:
    async def wrapped_node(*node_args: Any, **node_kwargs: Any) -> Any:
        del node_name, callback_handler
        return await original_func(*node_args, **node_kwargs)

    return wrapped_node


def _discover_compiled_graph_node_maps(compiled_graph: Any) -> list[Any]:
    candidate_maps = [
        getattr(compiled_graph, "nodes", None),
        getattr(compiled_graph, "_nodes", None),
    ]

    pregel = getattr(compiled_graph, "pregel", None)
    if pregel is None:
        pregel = getattr(compiled_graph, "_pregel", None)
    if pregel is not None:
        candidate_maps.extend(
            [
                getattr(pregel, "nodes", None),
                getattr(pregel, "_nodes", None),
            ]
        )

    return [node_map for node_map in candidate_maps if node_map is not None]


def _load_stategraph_class() -> type[Any] | None:
    try:
        module = importlib.import_module("langgraph.graph.state")
    except ImportError:
        return None

    state_graph_cls = getattr(module, "StateGraph", None)
    if isinstance(state_graph_cls, type):
        return state_graph_cls

    return None
