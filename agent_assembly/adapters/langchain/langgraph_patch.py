"""Backward-compatible shim for LangGraph patch utilities."""

import importlib  # noqa: F401 — re-exported for monkeypatch targets in tests

from agent_assembly.adapters.langgraph import patch as _impl

LangGraphPatch = _impl.LangGraphPatch
patch_stategraph_compile = _impl.patch_stategraph_compile

_PATCHED_FLAG = _impl._PATCHED_FLAG
_ORIGINAL_COMPILE = _impl._ORIGINAL_COMPILE
_NODE_WRAPPED_FLAG = _impl._NODE_WRAPPED_FLAG
_INVOKE_WRAPPED_FLAG = _impl._INVOKE_WRAPPED_FLAG

_extract_state = _impl._extract_state
_extract_config = _impl._extract_config
_extract_agent_id = _impl._extract_agent_id
_summarize_state_keys = _impl._summarize_state_keys
_compute_state_delta = _impl._compute_state_delta
_invoke_pre_node_hook = _impl._invoke_pre_node_hook
_invoke_post_node_hook = _impl._invoke_post_node_hook
_wrap_node_callable = _impl._wrap_node_callable
_make_sync_node_wrapper = _impl._make_sync_node_wrapper
_make_async_node_wrapper = _impl._make_async_node_wrapper
_make_assembly_node_wrapper = _impl._make_assembly_node_wrapper
_wrap_node_map = _impl._wrap_node_map
_wrap_compiled_graph_nodes = _impl._wrap_compiled_graph_nodes
_discover_compiled_graph_node_maps = _impl._discover_compiled_graph_node_maps
_apply_stategraph_compile_patch = _impl._apply_stategraph_compile_patch
_wrap_graph_invoke_fallback = _impl._wrap_graph_invoke_fallback
_record_node_enter = _impl._record_node_enter
_record_node_exit = _impl._record_node_exit
_load_stategraph_class = _impl._load_stategraph_class
