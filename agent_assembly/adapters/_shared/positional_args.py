"""Fold positional tool-call arguments into the governance-visible arg mapping.

Framework adapters build the ``tool_args`` mapping the policy inspects from a
tool call's *keyword* arguments. A tool invoked positionally
(``tool.invoke("secret")``) would otherwise present an empty or partial mapping,
so argument-CONTENT policy rules go blind to the positional values — the
allow/deny gate still fires on the tool name, but content rules never see the
data. Folding the positionals in (mirroring the smolagents/mcp handling) keeps
content policy able to inspect them.

This module deliberately imports only the stdlib so every leaf adapter can reuse
it without risking an import cycle through ``_shared.tool_governance`` (which
itself imports the CrewAI leaf helpers).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def merge_positional_tool_args(tool_args: dict[str, Any], args: tuple[Any, ...]) -> dict[str, Any]:
    """Fold positional call arguments into ``tool_args`` in place and return it.

    A single positional ``Mapping`` (the ``tool(payload)`` convenience shape) is
    flattened by key; any other positionals are recorded under ``arg{index}`` so
    their values remain visible to content policy even when the tool's real
    parameter names can't be recovered from the wrapper's ``*args`` signature.
    Existing keys win via ``setdefault`` so a real keyword argument is never
    overwritten by a positional fallback.

    Args:
        tool_args: Mapping already built from the call's keyword arguments.
        args: The positional arguments the tool was invoked with (excluding
            ``self``).

    Returns:
        The same ``tool_args`` dict, with positional values folded in.
    """
    if len(args) == 1 and isinstance(args[0], Mapping):
        for key, value in args[0].items():
            tool_args.setdefault(str(key), value)
    elif args:
        for index, value in enumerate(args):
            tool_args.setdefault(f"arg{index}", value)
    return tool_args
