"""LangChain adapter package."""

from agent_assembly.adapters.langchain.adapter import LangChainAdapter
from agent_assembly.adapters.langchain.callback_handler import AssemblyCallbackHandler
from agent_assembly.adapters.langchain.langgraph_patch import patch_stategraph_compile
from agent_assembly.adapters.langchain.patch import LangChainPatch
from agent_assembly.adapters.langchain.runtime import (
    auto_inject_callback_handler,
    get_active_callback_handler,
)
from agent_assembly.adapters.langgraph import LangGraphPatch

__all__ = [
    "LangChainAdapter",
    "AssemblyCallbackHandler",
    "LangChainPatch",
    "LangGraphPatch",
    "patch_stategraph_compile",
    "auto_inject_callback_handler",
    "get_active_callback_handler",
]
