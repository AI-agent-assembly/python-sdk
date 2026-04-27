"""LangGraph compile-time patching for governance interception."""

from __future__ import annotations

from typing import Any


def patch_stategraph_compile(callback_handler: Any) -> bool:
    """Patch `StateGraph.compile()` to attach runtime governance hooks."""
    del callback_handler
    return False
