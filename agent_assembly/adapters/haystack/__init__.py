"""Haystack adapter package.

Governs deepset Haystack 2.x agents by intercepting tool execution at
``haystack.tools.Tool.invoke`` — the single chokepoint through which both
direct ``Tool.invoke()`` calls and the ``Agent``/``ToolInvoker`` tool-call
path flow.  See ``patch.py`` for the hook-point rationale.
"""

from agent_assembly.adapters.haystack.adapter import HaystackAdapter
from agent_assembly.adapters.haystack.patch import HaystackPatch

__all__ = ["HaystackAdapter", "HaystackPatch"]
