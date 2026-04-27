"""LangGraph compile-time patching for governance interception."""

from __future__ import annotations

import importlib
import inspect
from typing import Any

_PATCHED_FLAG = "_agent_assembly_compile_patched"
_ORIGINAL_COMPILE = "_agent_assembly_original_compile"


def _invoke_pre_node_hook(callback_handler: Any, state: Any) -> None:
    method = getattr(callback_handler, "on_graph_node_start", None)
    if not callable(method):
        return None

    result = method(node_name="graph.invoke", state=state)
    if inspect.isawaitable(result):
        return None

    return None


def patch_stategraph_compile(callback_handler: Any) -> bool:
    """Patch `StateGraph.compile()` to attach runtime governance hooks."""
    try:
        module = importlib.import_module("langgraph.graph.state")
    except ImportError:
        return False

    state_graph_cls = getattr(module, "StateGraph", None)
    if state_graph_cls is None:
        return False

    if getattr(state_graph_cls, _PATCHED_FLAG, False):
        return True

    original_compile = state_graph_cls.compile

    def patched_compile(self: Any, *args: Any, **kwargs: Any) -> Any:
        compiled_graph = original_compile(self, *args, **kwargs)
        invoke = getattr(compiled_graph, "invoke", None)
        if callable(invoke):
            def wrapped_invoke(state: Any, *invoke_args: Any, **invoke_kwargs: Any) -> Any:
                _invoke_pre_node_hook(callback_handler, state)
                return invoke(state, *invoke_args, **invoke_kwargs)

            setattr(compiled_graph, "invoke", wrapped_invoke)
        return compiled_graph

    setattr(state_graph_cls, _ORIGINAL_COMPILE, original_compile)
    setattr(state_graph_cls, "compile", patched_compile)
    setattr(state_graph_cls, _PATCHED_FLAG, True)
    return True
