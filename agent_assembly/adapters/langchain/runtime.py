"""LangChain runtime wiring helpers."""

from __future__ import annotations

import warnings
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
    """Create and register the active callback handler instance.

    The active handler is a module-level singleton. Re-injecting with the *same*
    interceptor returns the existing handler unchanged (the matching-params
    re-init path, which ``init_assembly`` guards today). If a *different*
    interceptor is injected while one is already active, the stale handler is
    replaced rather than silently kept: today ``init_assembly`` blocks a
    mismatched re-init before reaching here, so this is defensive hardening for
    future refactors that might inject a differently-postured interceptor
    without a prior ``shutdown()`` clearing the singleton (AAASM-4831).
    """
    global _ACTIVE_CALLBACK_HANDLER

    with _RUNTIME_LOCK:
        if process_agent_id is not None:
            set_process_agent_id(process_agent_id)

        active = _ACTIVE_CALLBACK_HANDLER
        if active is not None:
            if active._interceptor is interceptor:
                return active
            warnings.warn(
                "auto_inject_callback_handler called with a different interceptor "
                "while a callback handler is already active; replacing the stale "
                "handler. Call the assembly context's shutdown() before re-initializing.",
                RuntimeWarning,
                stacklevel=2,
            )

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
