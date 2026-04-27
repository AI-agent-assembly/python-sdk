"""LangChain runtime wiring helpers."""

from __future__ import annotations

from threading import Lock
from typing import Any

from agent_assembly.adapters.langchain.callback_handler import AssemblyCallbackHandler
from agent_assembly.adapters.langchain.langgraph_patch import patch_stategraph_compile

_ACTIVE_CALLBACK_HANDLER: AssemblyCallbackHandler | None = None
_RUNTIME_LOCK = Lock()


def auto_inject_callback_handler(interceptor: Any) -> AssemblyCallbackHandler:
    """Create and register the active callback handler instance."""
    global _ACTIVE_CALLBACK_HANDLER

    with _RUNTIME_LOCK:
        if _ACTIVE_CALLBACK_HANDLER is not None:
            patch_stategraph_compile(_ACTIVE_CALLBACK_HANDLER)
            return _ACTIVE_CALLBACK_HANDLER

        handler = AssemblyCallbackHandler(interceptor)
        _ACTIVE_CALLBACK_HANDLER = handler
        patch_stategraph_compile(handler)
        return handler


def get_active_callback_handler() -> AssemblyCallbackHandler | None:
    """Return the current callback handler instance when one is registered."""
    return _ACTIVE_CALLBACK_HANDLER
