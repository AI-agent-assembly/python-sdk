"""Smolagents patch module.

Smolagents (Hugging Face, pip ``smolagents``) routes *every* tool execution
through ``smolagents.tools.Tool.__call__`` — both the ``ToolCallingAgent`` path
(``MultiStepAgent.execute_tool_call`` resolves the tool and calls ``tool(...)``)
and the ``CodeAgent`` path (tools are injected into the sandbox namespace and
invoked as plain callables, which dispatches to ``Tool.__call__``).  ``__call__``
runs ``self.forward(*args, **kwargs)`` to execute the tool body, so wrapping it is
the single chokepoint that lets governance observe the tool name + arguments and
decide *before* the body runs.

This is the SDK (in-process) interception layer: the wrapper denies before
``forward`` executes (fail-closed under ``enforce``) and records the result on
allow.  Reverting restores the original unbound ``__call__``.
"""

from __future__ import annotations

import importlib as importlib
from dataclasses import dataclass
from functools import wraps
from threading import local
from typing import Any

# Reuse the governance-decision plumbing proven by the CrewAI adapter so every
# framework normalizes verdicts and fail-closed posture identically.
from agent_assembly.adapters.crewai.patch import (
    _format_approval_rejected_message,
    _format_blocked_message,
    _get_pending_tool_approval_timeout_seconds,
    _interceptor_enforces,
    _invoke_sync_tool_check,
    _normalize_decision,
    _record_sync_tool_result,
    _wait_for_sync_tool_approval,
)

_TOOL_PATCHED_FLAG = "_agent_assembly_smolagents_tool_patched"
_ORIGINAL_TOOL_CALL = "_agent_assembly_original_smolagents_tool_call"

# ``sanitize_inputs_outputs`` is a smolagents-internal control flag on
# ``Tool.__call__``, never a tool input — strip it before reporting tool args to
# governance so policies match on the real arguments only.
_INTERNAL_CALL_KWARGS = frozenset({"sanitize_inputs_outputs"})

_AGENT_CONTEXT = local()


@dataclass(slots=True)
class SmolagentsPatch:
    """Applies smolagents runtime monkey-patching hooks."""

    callback_handler: Any

    def apply(self) -> bool:
        """Apply patch wiring and return whether smolagents is available."""
        tool_cls = _load_smolagents_tool_class()
        if tool_cls is None:
            return False

        _apply_tool_call_patch(tool_cls, self.callback_handler)
        return True

    def revert(self) -> None:
        """Revert smolagents runtime monkey patches when available."""
        tool_cls = _load_smolagents_tool_class()
        if tool_cls is not None:
            _revert_tool_call_patch(tool_cls)
        return None


def _load_smolagents_tool_class() -> type[Any] | None:
    try:
        module = importlib.import_module("smolagents")
    except ImportError:
        return None

    tool_cls = getattr(module, "Tool", None)
    if isinstance(tool_cls, type):
        return tool_cls
    return None


def _set_thread_local_agent_id(agent_id: str | None) -> None:
    _AGENT_CONTEXT.agent_id = agent_id


def _get_thread_local_agent_id() -> str | None:
    agent_id = getattr(_AGENT_CONTEXT, "agent_id", None)
    if isinstance(agent_id, str) and agent_id:
        return agent_id
    return None


def _extract_tool_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Build the governance-visible argument mapping for a tool call.

    smolagents tools may be invoked with keyword inputs (``tool(text="hi")``) or a
    single positional dict (``tool({"text": "hi"})`` — the dict-arg convenience
    path in ``Tool.__call__``).  Both shapes are flattened so the policy sees the
    real tool inputs.  Framework-internal control kwargs are excluded.
    """
    tool_args: dict[str, Any] = {key: value for key, value in kwargs.items() if key not in _INTERNAL_CALL_KWARGS}

    if len(args) == 1 and isinstance(args[0], dict):
        for key, value in args[0].items():
            tool_args.setdefault(str(key), value)
    elif args:
        for index, value in enumerate(args):
            tool_args.setdefault(f"arg{index}", value)

    return tool_args


def _resolve_tool_name(tool: Any) -> str:
    name = getattr(tool, "name", None)
    if isinstance(name, str) and name:
        return name
    return str(tool.__class__.__name__)


def _apply_tool_call_patch(tool_cls: type[Any], callback_handler: Any) -> None:
    if getattr(tool_cls, _TOOL_PATCHED_FLAG, False):
        return None

    original_call = tool_cls.__call__
    enforce = _interceptor_enforces(callback_handler)

    @wraps(original_call)
    def patched_call(self: Any, *args: Any, **kwargs: Any) -> Any:
        tool_name = _resolve_tool_name(self)
        tool_args = _extract_tool_args(args, kwargs)
        agent_id = _get_thread_local_agent_id()

        decision = _invoke_sync_tool_check(
            callback_handler,
            tool_name=tool_name,
            tool_args=tool_args,
            agent_id=agent_id,
        )
        status, reason = _normalize_decision(decision, enforce=enforce)

        is_pending_flow = False
        if status == "pending":
            is_pending_flow = True
            timeout_seconds = _get_pending_tool_approval_timeout_seconds(callback_handler)
            final_decision = _wait_for_sync_tool_approval(
                callback_handler,
                tool_name=tool_name,
                timeout_seconds=timeout_seconds,
                tool_args=tool_args,
                agent_id=agent_id,
            )
            status, reason = _normalize_decision(final_decision, enforce=enforce)

        if status == "deny":
            if is_pending_flow:
                return _format_approval_rejected_message(reason)
            return _format_blocked_message(reason)

        result = original_call(self, *args, **kwargs)
        _record_sync_tool_result(callback_handler, tool_name=tool_name, result=result)
        return result

    setattr(tool_cls, _ORIGINAL_TOOL_CALL, original_call)
    tool_cls.__call__ = patched_call
    setattr(tool_cls, _TOOL_PATCHED_FLAG, True)
    return None


def _revert_tool_call_patch(tool_cls: type[Any]) -> None:
    if not getattr(tool_cls, _TOOL_PATCHED_FLAG, False):
        return None

    original_call = getattr(tool_cls, _ORIGINAL_TOOL_CALL, None)
    if callable(original_call):
        tool_cls.__call__ = original_call

    if hasattr(tool_cls, _ORIGINAL_TOOL_CALL):
        delattr(tool_cls, _ORIGINAL_TOOL_CALL)
    if hasattr(tool_cls, _TOOL_PATCHED_FLAG):
        delattr(tool_cls, _TOOL_PATCHED_FLAG)
    return None
