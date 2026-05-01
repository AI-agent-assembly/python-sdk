"""LangGraph patch module."""

from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from typing import Any

_PATCHED_FLAG = "_agent_assembly_compile_patched"
_ORIGINAL_COMPILE = "_agent_assembly_original_compile"
_NODE_WRAPPED_FLAG = "_agent_assembly_node_wrapped"
_INVOKE_WRAPPED_FLAG = "_agent_assembly_invoke_wrapped"


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
        _apply_stategraph_compile_patch(state_graph_cls, self.callback_handler)
        return True

    def revert(self) -> None:
        """Revert state graph compile patch when it is currently active."""
        state_graph_cls = _load_stategraph_class()
        if state_graph_cls is None:
            return None
        _revert_stategraph_compile_patch(state_graph_cls)
        return None


def patch_stategraph_compile(callback_handler: Any) -> bool:
    """Backward-compatible helper used by existing runtime wiring."""
    return LangGraphPatch(callback_handler=callback_handler).apply()


def _invoke_pre_node_hook(callback_handler: Any, node_name: str, state: object) -> None:
    """Backward-compatible pre-node hook helper."""
    _record_node_enter(
        callback_handler,
        node_name=node_name,
        state=state,
        config=None,
    )
    return None


def _invoke_post_node_hook(
    callback_handler: Any,
    node_name: str,
    state: object,
    result: object,
) -> None:
    """Backward-compatible post-node hook helper."""
    _record_node_exit(
        callback_handler,
        node_name=node_name,
        previous_state=state,
        next_state=result,
        config=None,
    )
    return None


def _wrap_node_callable(node_name: str, node_func: Any, callback_handler: Any) -> Any:
    """Backward-compatible node wrapper helper."""
    return _make_assembly_node_wrapper(node_name, node_func, callback_handler)


def _extract_state(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    if args:
        return args[0]
    return kwargs.get("state")


def _extract_config(args: tuple[Any, ...], kwargs: dict[str, Any]) -> object:
    if "config" in kwargs:
        return kwargs["config"]
    if len(args) >= 2:
        return args[1]
    return None


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
        state = _extract_state(node_args, node_kwargs)
        config = _extract_config(node_args, node_kwargs)
        _record_node_enter(callback_handler, node_name=node_name, state=state, config=config)
        result = original_func(*node_args, **node_kwargs)
        _record_node_exit(
            callback_handler,
            node_name=node_name,
            previous_state=state,
            next_state=result,
            config=config,
        )
        return result

    return wrapped_node


def _make_async_node_wrapper(node_name: str, original_func: Any, callback_handler: Any) -> Any:
    async def wrapped_node(*node_args: Any, **node_kwargs: Any) -> Any:
        state = _extract_state(node_args, node_kwargs)
        config = _extract_config(node_args, node_kwargs)
        _record_node_enter(callback_handler, node_name=node_name, state=state, config=config)
        result = await original_func(*node_args, **node_kwargs)
        _record_node_exit(
            callback_handler,
            node_name=node_name,
            previous_state=state,
            next_state=result,
            config=config,
        )
        return result

    return wrapped_node


def _make_assembly_node_wrapper(node_name: str, original_func: Any, callback_handler: Any) -> Any:
    if getattr(original_func, _NODE_WRAPPED_FLAG, False):
        return original_func

    if inspect.iscoroutinefunction(original_func):
        wrapped = _make_async_node_wrapper(node_name, original_func, callback_handler)
    else:
        wrapped = _make_sync_node_wrapper(node_name, original_func, callback_handler)

    setattr(wrapped, _NODE_WRAPPED_FLAG, True)
    return wrapped


def _wrap_node_map(node_map: Any, callback_handler: Any) -> bool:
    items_method = getattr(node_map, "items", None)
    if not callable(items_method):
        return False

    wrapped_any = False
    for node_name, node_executor in list(items_method()):
        if callable(node_executor):
            wrapped_executor = _make_assembly_node_wrapper(str(node_name), node_executor, callback_handler)
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
            wrapped_invoke = _make_assembly_node_wrapper(str(node_name), invoke, callback_handler)
            setattr(node_executor, "invoke", wrapped_invoke)
            wrapped_any = True

        ainvoke = getattr(node_executor, "ainvoke", None)
        if callable(ainvoke):
            wrapped_ainvoke = _make_assembly_node_wrapper(str(node_name), ainvoke, callback_handler)
            setattr(node_executor, "ainvoke", wrapped_ainvoke)
            wrapped_any = True

    return wrapped_any


def _wrap_compiled_graph_nodes(compiled_graph: Any, callback_handler: Any) -> bool:
    wrapped_any = False
    for node_map in _discover_compiled_graph_node_maps(compiled_graph):
        if _wrap_node_map(node_map, callback_handler):
            wrapped_any = True
    return wrapped_any


def _apply_stategraph_compile_patch(state_graph_cls: type[Any], callback_handler: Any) -> None:
    original_compile = state_graph_cls.compile

    def patched_compile(self: Any, *args: Any, **kwargs: Any) -> Any:
        compiled_graph = original_compile(self, *args, **kwargs)
        nodes_wrapped = _wrap_compiled_graph_nodes(compiled_graph, callback_handler)
        if not nodes_wrapped:
            _wrap_graph_invoke_fallback(compiled_graph, callback_handler)
        return compiled_graph

    setattr(state_graph_cls, _ORIGINAL_COMPILE, original_compile)
    setattr(state_graph_cls, "compile", patched_compile)
    setattr(state_graph_cls, _PATCHED_FLAG, True)


def _revert_stategraph_compile_patch(state_graph_cls: type[Any]) -> None:
    if not getattr(state_graph_cls, _PATCHED_FLAG, False):
        return None

    original_compile = getattr(state_graph_cls, _ORIGINAL_COMPILE, None)
    if callable(original_compile):
        setattr(state_graph_cls, "compile", original_compile)

    if hasattr(state_graph_cls, _ORIGINAL_COMPILE):
        delattr(state_graph_cls, _ORIGINAL_COMPILE)
    if hasattr(state_graph_cls, _PATCHED_FLAG):
        delattr(state_graph_cls, _PATCHED_FLAG)
    return None


def _wrap_graph_invoke_fallback(compiled_graph: Any, callback_handler: Any) -> None:
    invoke = getattr(compiled_graph, "invoke", None)
    if not callable(invoke) or getattr(invoke, _INVOKE_WRAPPED_FLAG, False):
        return None

    if inspect.iscoroutinefunction(invoke):

        async def wrapped_async_invoke(*invoke_args: Any, **invoke_kwargs: Any) -> Any:
            state = _extract_state(invoke_args, invoke_kwargs)
            config = _extract_config(invoke_args, invoke_kwargs)
            _record_node_enter(callback_handler, node_name="graph.invoke", state=state, config=config)
            result = await invoke(*invoke_args, **invoke_kwargs)
            _record_node_exit(
                callback_handler,
                node_name="graph.invoke",
                previous_state=state,
                next_state=result,
                config=config,
            )
            return result

        wrapped_invoke: Any = wrapped_async_invoke
    else:

        def wrapped_sync_invoke(*invoke_args: Any, **invoke_kwargs: Any) -> Any:
            state = _extract_state(invoke_args, invoke_kwargs)
            config = _extract_config(invoke_args, invoke_kwargs)
            _record_node_enter(callback_handler, node_name="graph.invoke", state=state, config=config)
            result = invoke(*invoke_args, **invoke_kwargs)
            _record_node_exit(
                callback_handler,
                node_name="graph.invoke",
                previous_state=state,
                next_state=result,
                config=config,
            )
            return result

        wrapped_invoke = wrapped_sync_invoke

    setattr(wrapped_invoke, _INVOKE_WRAPPED_FLAG, True)
    setattr(compiled_graph, "invoke", wrapped_invoke)


def _record_node_enter(callback_handler: Any, *, node_name: str, state: object, config: object) -> None:
    method = getattr(callback_handler, "on_graph_node_start", None)
    if not callable(method):
        return None

    hook_kwargs = {
        "node_name": node_name,
        "agent_id": _extract_agent_id(config),
        "state": state,
        "state_keys": _summarize_state_keys(state),
        "config": config,
    }
    try:
        method(**hook_kwargs)
    except TypeError as exc:
        if not _is_call_signature_type_error(exc):
            raise
        method(node_name=node_name, state=state)
    return None


def _record_node_exit(
    callback_handler: Any,
    *,
    node_name: str,
    previous_state: object,
    next_state: object,
    config: object,
) -> None:
    method = getattr(callback_handler, "on_graph_node_end", None)
    if not callable(method):
        return None

    hook_kwargs = {
        "node_name": node_name,
        "agent_id": _extract_agent_id(config),
        "state": previous_state,
        "result": next_state,
        "state_delta": _compute_state_delta(previous_state, next_state),
        "config": config,
    }
    try:
        method(**hook_kwargs)
    except TypeError as exc:
        if not _is_call_signature_type_error(exc):
            raise
        method(node_name=node_name, state=previous_state, result=next_state)
    return None


def _is_call_signature_type_error(error: TypeError) -> bool:
    message = str(error)
    signature_markers = (
        "unexpected keyword argument",
        "missing 1 required positional argument",
        "missing required positional argument",
        "takes ",
        "positional arguments but",
        "keyword-only argument",
    )
    return any(marker in message for marker in signature_markers)


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
