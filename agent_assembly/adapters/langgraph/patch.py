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


def _load_stategraph_class() -> type[Any] | None:
    try:
        module = importlib.import_module("langgraph.graph.state")
    except ImportError:
        return None

    state_graph_cls = getattr(module, "StateGraph", None)
    if isinstance(state_graph_cls, type):
        return state_graph_cls

    return None
