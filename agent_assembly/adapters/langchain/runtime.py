"""LangChain runtime wiring helpers."""

from __future__ import annotations

from typing import Any

from agent_assembly.adapters.langchain.callback_handler import AssemblyCallbackHandler

_ACTIVE_CALLBACK_HANDLER: AssemblyCallbackHandler | None = None


def auto_inject_callback_handler(interceptor: Any) -> AssemblyCallbackHandler:
    """Create and register the active callback handler instance."""
    global _ACTIVE_CALLBACK_HANDLER

    handler = AssemblyCallbackHandler(interceptor)
    _ACTIVE_CALLBACK_HANDLER = handler
    return handler


def get_active_callback_handler() -> AssemblyCallbackHandler | None:
    """Return the current callback handler instance when one is registered."""
    return _ACTIVE_CALLBACK_HANDLER
