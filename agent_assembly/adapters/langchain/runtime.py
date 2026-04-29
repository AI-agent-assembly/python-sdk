"""LangChain runtime wiring helpers."""

from __future__ import annotations

from threading import Lock
from typing import Any

from agent_assembly.adapters.langchain.callback_handler import AssemblyCallbackHandler
from agent_assembly.adapters.pydantic_ai.patch import set_process_agent_id

_ACTIVE_CALLBACK_HANDLER: AssemblyCallbackHandler | None = None
_RUNTIME_LOCK = Lock()


def auto_inject_callback_handler(
    interceptor: Any,
    *,
    process_agent_id: str | None = None,
) -> AssemblyCallbackHandler:
    """Create and register the active callback handler instance."""
    global _ACTIVE_CALLBACK_HANDLER

    with _RUNTIME_LOCK:
        if process_agent_id is not None:
            set_process_agent_id(process_agent_id)

        if _ACTIVE_CALLBACK_HANDLER is not None:
            return _ACTIVE_CALLBACK_HANDLER

        handler = AssemblyCallbackHandler(interceptor)
        _ACTIVE_CALLBACK_HANDLER = handler
        return handler


def get_active_callback_handler() -> AssemblyCallbackHandler | None:
    """Return the current callback handler instance when one is registered."""
    return _ACTIVE_CALLBACK_HANDLER


def _reset_runtime_state_for_tests() -> None:
    global _ACTIVE_CALLBACK_HANDLER

    with _RUNTIME_LOCK:
        _ACTIVE_CALLBACK_HANDLER = None
