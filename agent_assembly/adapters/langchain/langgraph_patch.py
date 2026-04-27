"""LangGraph compile-time patching for governance interception."""

from __future__ import annotations

import importlib
import inspect
from typing import Any

_PATCHED_FLAG = "_agent_assembly_compile_patched"
_ORIGINAL_COMPILE = "_agent_assembly_original_compile"
_NODE_WRAPPED_FLAG = "_agent_assembly_node_wrapped"
_INVOKE_WRAPPED_FLAG = "_agent_assembly_invoke_wrapped"


def _extract_state(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    if args:
        return args[0]
    return kwargs.get("state")


def _invoke_pre_node_hook(callback_handler: Any, node_name: str, state: Any) -> None:
    method = getattr(callback_handler, "on_graph_node_start", None)
    if not callable(method):
        return None

    result = method(node_name=node_name, state=state)
    if inspect.isawaitable(result):
        return None

    return None


def _invoke_post_node_hook(callback_handler: Any, node_name: str, state: Any, result: Any) -> None:
    method = getattr(callback_handler, "on_graph_node_end", None)
    if not callable(method):
        return None

    callback_result = method(node_name=node_name, state=state, result=result)
    if inspect.isawaitable(callback_result):
        return None

    return None


def _wrap_node_callable(node_name: str, node_callable: Any, callback_handler: Any) -> Any:
    if getattr(node_callable, _NODE_WRAPPED_FLAG, False):
        return node_callable

    def wrapped_node(*node_args: Any, **node_kwargs: Any) -> Any:
        state = _extract_state(node_args, node_kwargs)
        _invoke_pre_node_hook(callback_handler, node_name=node_name, state=state)

        node_result = node_callable(*node_args, **node_kwargs)
        if inspect.isawaitable(node_result):
            async def awaited_node_result() -> Any:
                resolved_result = await node_result
                _invoke_post_node_hook(
                    callback_handler,
                    node_name=node_name,
                    state=state,
                    result=resolved_result,
                )
                return resolved_result

            return awaited_node_result()

        _invoke_post_node_hook(
            callback_handler,
            node_name=node_name,
            state=state,
            result=node_result,
        )
        return node_result

    setattr(wrapped_node, _NODE_WRAPPED_FLAG, True)
    return wrapped_node


def _wrap_node_map(node_map: Any, callback_handler: Any) -> bool:
    items_method = getattr(node_map, "items", None)
    if not callable(items_method):
        return False

    wrapped_any = False
    for node_name, node_executor in list(items_method()):
        if callable(node_executor):
            wrapped_executor = _wrap_node_callable(str(node_name), node_executor, callback_handler)
            if wrapped_executor is node_executor:
                continue
            try:
                node_map[node_name] = wrapped_executor
            except Exception:
                continue
            wrapped_any = True
            continue

        invoke = getattr(node_executor, "invoke", None)
        if callable(invoke):
            setattr(
                node_executor,
                "invoke",
                _wrap_node_callable(str(node_name), invoke, callback_handler),
            )
            wrapped_any = True

        ainvoke = getattr(node_executor, "ainvoke", None)
        if callable(ainvoke):
            setattr(
                node_executor,
                "ainvoke",
                _wrap_node_callable(str(node_name), ainvoke, callback_handler),
            )
            wrapped_any = True

    return wrapped_any


def _wrap_compiled_graph_nodes(compiled_graph: Any, callback_handler: Any) -> bool:
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

    wrapped_any = False
    for node_map in candidate_maps:
        if node_map is None:
            continue
        if _wrap_node_map(node_map, callback_handler):
            wrapped_any = True

    return wrapped_any


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
        nodes_wrapped = _wrap_compiled_graph_nodes(compiled_graph, callback_handler)
        if not nodes_wrapped:
            invoke = getattr(compiled_graph, "invoke", None)
            if callable(invoke) and not getattr(invoke, _INVOKE_WRAPPED_FLAG, False):
                def wrapped_invoke(*invoke_args: Any, **invoke_kwargs: Any) -> Any:
                    state = _extract_state(invoke_args, invoke_kwargs)
                    _invoke_pre_node_hook(callback_handler, node_name="graph.invoke", state=state)

                    invoke_result = invoke(*invoke_args, **invoke_kwargs)
                    if inspect.isawaitable(invoke_result):
                        async def awaited_invoke_result() -> Any:
                            resolved_result = await invoke_result
                            _invoke_post_node_hook(
                                callback_handler,
                                node_name="graph.invoke",
                                state=state,
                                result=resolved_result,
                            )
                            return resolved_result

                        return awaited_invoke_result()

                    _invoke_post_node_hook(
                        callback_handler,
                        node_name="graph.invoke",
                        state=state,
                        result=invoke_result,
                    )
                    return invoke_result

                setattr(wrapped_invoke, _INVOKE_WRAPPED_FLAG, True)
                setattr(compiled_graph, "invoke", wrapped_invoke)
        return compiled_graph

    setattr(state_graph_cls, _ORIGINAL_COMPILE, original_compile)
    setattr(state_graph_cls, "compile", patched_compile)
    setattr(state_graph_cls, _PATCHED_FLAG, True)
    return True
