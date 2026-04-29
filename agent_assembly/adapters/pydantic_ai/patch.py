"""Pydantic AI patch module."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Any

_TOOLS_PATCHED_FLAG = "_agent_assembly_pydantic_ai_tools_patched"
_ORIGINAL_TOOL_RUN = "_agent_assembly_original_pydantic_ai_tool_run"


@dataclass(slots=True)
class PydanticAIPatch:
    """Applies Pydantic AI runtime monkey-patching hooks."""

    callback_handler: Any

    def apply(self) -> bool:
        """Apply patch wiring and return whether Pydantic AI is available."""
        tool_cls = _load_pydantic_ai_tool_class()
        if tool_cls is None:
            return False
        _apply_tool_run_patch(tool_cls, self.callback_handler)
        return True


def _load_pydantic_ai_tool_class() -> type[Any] | None:
    try:
        module = importlib.import_module("pydantic_ai.tools")
    except ImportError:
        return None

    tool_cls = getattr(module, "Tool", None)
    if isinstance(tool_cls, type):
        return tool_cls
    return None


def _apply_tool_run_patch(tool_cls: type[Any], callback_handler: Any) -> None:
    del callback_handler
    if getattr(tool_cls, _TOOLS_PATCHED_FLAG, False):
        return None

    setattr(tool_cls, _TOOLS_PATCHED_FLAG, True)
