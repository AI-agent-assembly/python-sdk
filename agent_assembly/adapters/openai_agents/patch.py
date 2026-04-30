"""OpenAI Agents patch module."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import importlib.util
from typing import Any

_ORIGINAL_FUNCTION_TOOL_CALL = "_agent_assembly_original_openai_agents_function_tool_call"
_PATCHED_FLAG = "_agent_assembly_openai_agents_function_tool_patched"
_PROCESS_AGENT_ID: str | None = None


@dataclass(slots=True)
class OpenAIAgentsPatch:
    """Patch placeholder for OpenAI Agents SDK interception."""

    callback_handler: Any
    process_agent_id: str | None = None

    def apply(self) -> bool:
        set_process_agent_id(self.process_agent_id)
        _ = self.callback_handler
        return _is_openai_agents_available()

    def revert(self) -> None:
        set_process_agent_id(None)
        return None


def _is_openai_agents_available() -> bool:
    return importlib.util.find_spec("openai.agents") is not None


def set_process_agent_id(agent_id: str | None) -> None:
    global _PROCESS_AGENT_ID
    _PROCESS_AGENT_ID = agent_id


def _get_process_agent_id() -> str | None:
    if isinstance(_PROCESS_AGENT_ID, str) and _PROCESS_AGENT_ID:
        return _PROCESS_AGENT_ID
    return None


def _load_openai_agents_function_tool_class() -> type[Any] | None:
    try:
        module = importlib.import_module("openai.agents")
    except ImportError:
        return None

    function_tool_cls = getattr(module, "FunctionTool", None)
    if isinstance(function_tool_cls, type):
        return function_tool_cls
    return None
