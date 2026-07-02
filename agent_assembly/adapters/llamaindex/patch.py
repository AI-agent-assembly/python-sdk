"""LlamaIndex patch module.

Installs the SDK-layer (in-process) governance hook for LlamaIndex by
monkey-patching the concrete tool-execution methods that an agent actually
drives. LlamaIndex routes every tool invocation through a ``BaseTool``
subclass, but ``BaseTool.call`` / ``acall`` are *abstract* — the real bodies
live on concrete classes such as ``FunctionTool``. The modern agent stack
(``FunctionAgent`` / ``ReActAgent`` via ``AgentWorkflow``) awaits
``tool.acall(...)``; the legacy / sync path calls ``tool.call(...)``. We patch
both so a tool's underlying function never runs when policy denies it.

The deny path returns a ``ToolOutput`` (not a raw string) so the agent loop
receives a well-formed, ``is_error``-flagged result instead of crashing — the
tool body is the thing that must not execute, which is the security-relevant
invariant (AAASM-3536).

Decision normalization and fail-closed-under-enforce semantics are shared with
the CrewAI patch (AAASM-3107) rather than re-implemented, so every adapter
treats an unknown / malformed verdict identically.
"""

from __future__ import annotations

import importlib as importlib
from dataclasses import dataclass
from functools import wraps
from threading import local
from typing import Any

from agent_assembly.adapters.crewai.patch import (
    _get_pending_tool_approval_timeout_seconds as _resolve_pending_timeout_seconds,
)
from agent_assembly.adapters.crewai.patch import (
    _interceptor_enforces,
    _missing_interceptor_decision,
    _normalize_decision,
)

_ORIGINAL_TOOL_CALL = "_agent_assembly_original_llamaindex_tool_call"
_ORIGINAL_TOOL_ACALL = "_agent_assembly_original_llamaindex_tool_acall"
_TOOL_CALL_PATCHED_FLAG = "_agent_assembly_llamaindex_tool_call_patched"
_TOOL_ACALL_PATCHED_FLAG = "_agent_assembly_llamaindex_tool_acall_patched"

_AGENT_CONTEXT = local()


@dataclass(slots=True)
class LlamaIndexPatch:
    """Applies LlamaIndex runtime monkey-patching hooks.

    Patches the concrete ``FunctionTool`` sync (``call``) and async (``acall``)
    execution methods. ``apply()`` returns whether a hook was installed so the
    adapter / registry can treat a missing framework as a no-op rather than an
    error.
    """

    callback_handler: Any
    process_agent_id: str | None = None

    def apply(self) -> bool:
        """Patch the LlamaIndex tool-execution methods.

        Returns:
            ``True`` when at least one tool hook was installed, ``False`` when
            LlamaIndex is not importable or exposes no patchable tool class.
        """
        set_process_agent_id(self.process_agent_id)

        tool_cls = _load_llamaindex_function_tool_class()
        if tool_cls is None:
            set_process_agent_id(None)
            return False

        sync_hooked = _apply_tool_call_patch(tool_cls, self.callback_handler)
        async_hooked = _apply_tool_acall_patch(tool_cls, self.callback_handler)

        if not (sync_hooked or async_hooked):
            set_process_agent_id(None)
            return False
        return True

    def revert(self) -> None:
        """Revert LlamaIndex tool patches when available."""
        tool_cls = _load_llamaindex_function_tool_class()
        if tool_cls is not None:
            _revert_tool_call_patch(tool_cls)
            _revert_tool_acall_patch(tool_cls)
        set_process_agent_id(None)
        return None


def set_process_agent_id(agent_id: str | None) -> None:
    """Store the process-level agent ID used for event attribution."""
    _AGENT_CONTEXT.process_agent_id = agent_id


def _get_process_agent_id() -> str | None:
    agent_id = getattr(_AGENT_CONTEXT, "process_agent_id", None)
    if isinstance(agent_id, str) and agent_id:
        return agent_id
    return None


def _load_llamaindex_function_tool_class() -> type[Any] | None:
    try:
        module = importlib.import_module("llama_index.core.tools")
    except ImportError:
        return None

    tool_cls = getattr(module, "FunctionTool", None)
    if isinstance(tool_cls, type):
        return tool_cls
    return None


def _load_tool_output_class() -> type[Any] | None:
    try:
        module = importlib.import_module("llama_index.core.tools.types")
    except ImportError:
        return None

    output_cls = getattr(module, "ToolOutput", None)
    if isinstance(output_cls, type):
        return output_cls
    return None


def _tool_name(tool: Any) -> str:
    metadata = getattr(tool, "metadata", None)
    if metadata is not None:
        get_name = getattr(metadata, "get_name", None)
        if callable(get_name):
            try:
                name = get_name()
            except Exception:
                name = None
            if isinstance(name, str) and name:
                return name
        name = getattr(metadata, "name", None)
        if isinstance(name, str) and name:
            return name
    return str(tool.__class__.__name__)


def _format_blocked_message(reason: str | None) -> str:
    reason_text = reason or "No reason provided."
    return f"[BLOCKED by governance policy] {reason_text}. Please choose a different approach to accomplish this task."


def _format_approval_rejected_message(reason: str | None) -> str:
    reason_text = reason or "No reason provided."
    return f"[APPROVAL REJECTED] Action was reviewed and denied: {reason_text}"


def _denied_tool_output(tool: Any, *, tool_name: str, message: str) -> Any:
    """Build a denial ``ToolOutput`` so the agent loop sees an error result.

    Falls back to the raw string only if ``ToolOutput`` cannot be imported,
    which keeps the deny path functioning even on an unexpected LlamaIndex
    layout — the security invariant (the tool body never runs) holds either way.
    """
    output_cls = _load_tool_output_class()
    if output_cls is None:
        return message
    return output_cls(
        content=message,
        tool_name=tool_name,
        raw_input={},
        raw_output=message,
        is_error=True,
    )


def _invoke_tool_check(
    callback_handler: Any,
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    agent_id: str | None,
) -> object:
    method = getattr(callback_handler, "check_tool_start", None)
    if callable(method):
        return method(
            serialized={"name": tool_name},
            input_str=str(tool_args),
            tool_name=tool_name,
            args=tool_args,
            agent_id=agent_id,
        )
    return _missing_interceptor_decision(callback_handler)


def _wait_for_tool_approval(
    callback_handler: Any,
    *,
    tool_name: str,
    timeout_seconds: int,
    tool_args: dict[str, Any],
    agent_id: str | None,
) -> object:
    method = getattr(callback_handler, "wait_for_tool_approval", None)
    if callable(method):
        return method(
            tool_name=tool_name,
            timeout_seconds=timeout_seconds,
            args=tool_args,
            agent_id=agent_id,
        )
    return {"status": "deny", "reason": "Approval handler is unavailable."}


def _record_tool_result(callback_handler: Any, *, tool_name: str, result: object) -> None:
    record_method = getattr(callback_handler, "record_result", None)
    if callable(record_method):
        record_method(tool_name=tool_name, result=result)
        return None

    tool_end_method = getattr(callback_handler, "on_tool_end", None)
    if callable(tool_end_method):
        tool_end_method(output=result, tool_name=tool_name)
    return None


def _resolve_governance_decision(
    callback_handler: Any,
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    agent_id: str | None,
    enforce: bool,
) -> tuple[str, str | None, bool]:
    """Run the pre-execution check and any pending-approval wait.

    Returns ``(status, reason, is_pending_flow)`` where ``status`` is the final
    normalized verdict (``allow`` / ``deny`` / ``pending``) — ``pending`` only
    survives when no approval handler resolved it.
    """
    decision = _invoke_tool_check(
        callback_handler,
        tool_name=tool_name,
        tool_args=tool_args,
        agent_id=agent_id,
    )
    status, reason = _normalize_decision(decision, enforce=enforce)
    is_pending_flow = False
    if status == "pending":
        is_pending_flow = True
        timeout_seconds = _resolve_pending_timeout_seconds(callback_handler)
        final_decision = _wait_for_tool_approval(
            callback_handler,
            tool_name=tool_name,
            timeout_seconds=timeout_seconds,
            tool_args=tool_args,
            agent_id=agent_id,
        )
        status, reason = _normalize_decision(final_decision, enforce=enforce)
    return status, reason, is_pending_flow


def _apply_tool_call_patch(tool_cls: type[Any], callback_handler: Any) -> bool:
    if "call" not in tool_cls.__dict__:
        return False
    if getattr(tool_cls, _TOOL_CALL_PATCHED_FLAG, False):
        return True

    # Capture the raw class-dict descriptor, not the attribute. LlamaIndex's
    # instrumentation wraps ``call`` so ``tool_cls.call`` yields a fresh
    # ``BoundFunctionWrapper`` on every access; the ``__dict__`` entry is the
    # stable original to restore on revert.
    original_call = tool_cls.__dict__["call"]
    enforce = _interceptor_enforces(callback_handler)

    @wraps(original_call)
    def patched_call(self: Any, *args: Any, **kwargs: Any) -> Any:
        tool_name = _tool_name(self)
        tool_args = dict(kwargs)
        agent_id = _get_process_agent_id()
        status, reason, is_pending_flow = _resolve_governance_decision(
            callback_handler,
            tool_name=tool_name,
            tool_args=tool_args,
            agent_id=agent_id,
            enforce=enforce,
        )
        if status == "deny":
            message = _format_approval_rejected_message(reason) if is_pending_flow else _format_blocked_message(reason)
            return _denied_tool_output(self, tool_name=tool_name, message=message)

        # Invoke the original via the descriptor protocol so the instance binds
        # as ``self``. LlamaIndex wraps ``call`` with an instrumentation
        # (``@dispatcher.span``) decorator whose signature re-binding rejects a
        # plain ``original_call(self, ...)`` unbound call (it loses ``self``).
        result = original_call.__get__(self, type(self))(*args, **kwargs)
        _record_tool_result(callback_handler, tool_name=tool_name, result=result)
        return result

    setattr(tool_cls, _ORIGINAL_TOOL_CALL, original_call)
    tool_cls.call = patched_call
    setattr(tool_cls, _TOOL_CALL_PATCHED_FLAG, True)
    return True


def _apply_tool_acall_patch(tool_cls: type[Any], callback_handler: Any) -> bool:
    if "acall" not in tool_cls.__dict__:
        return False
    if getattr(tool_cls, _TOOL_ACALL_PATCHED_FLAG, False):
        return True

    # See ``_apply_tool_call_patch`` — capture the stable ``__dict__`` descriptor.
    original_acall = tool_cls.__dict__["acall"]
    enforce = _interceptor_enforces(callback_handler)

    @wraps(original_acall)
    async def patched_acall(self: Any, *args: Any, **kwargs: Any) -> Any:
        tool_name = _tool_name(self)
        tool_args = dict(kwargs)
        agent_id = _get_process_agent_id()
        status, reason, is_pending_flow = _resolve_governance_decision(
            callback_handler,
            tool_name=tool_name,
            tool_args=tool_args,
            agent_id=agent_id,
            enforce=enforce,
        )
        if status == "deny":
            message = _format_approval_rejected_message(reason) if is_pending_flow else _format_blocked_message(reason)
            return _denied_tool_output(self, tool_name=tool_name, message=message)

        # See ``patched_call`` for why the original is invoked via the
        # descriptor protocol rather than ``original_acall(self, ...)``.
        result = await original_acall.__get__(self, type(self))(*args, **kwargs)
        _record_tool_result(callback_handler, tool_name=tool_name, result=result)
        return result

    setattr(tool_cls, _ORIGINAL_TOOL_ACALL, original_acall)
    tool_cls.acall = patched_acall
    setattr(tool_cls, _TOOL_ACALL_PATCHED_FLAG, True)
    return True


def _revert_tool_call_patch(tool_cls: type[Any]) -> None:
    if not getattr(tool_cls, _TOOL_CALL_PATCHED_FLAG, False):
        return None
    original_call = getattr(tool_cls, _ORIGINAL_TOOL_CALL, None)
    if callable(original_call):
        tool_cls.call = original_call
    for attr in (_ORIGINAL_TOOL_CALL, _TOOL_CALL_PATCHED_FLAG):
        if hasattr(tool_cls, attr):
            delattr(tool_cls, attr)
    return None


def _revert_tool_acall_patch(tool_cls: type[Any]) -> None:
    if not getattr(tool_cls, _TOOL_ACALL_PATCHED_FLAG, False):
        return None
    original_acall = getattr(tool_cls, _ORIGINAL_TOOL_ACALL, None)
    if callable(original_acall):
        tool_cls.acall = original_acall
    for attr in (_ORIGINAL_TOOL_ACALL, _TOOL_ACALL_PATCHED_FLAG):
        if hasattr(tool_cls, attr):
            delattr(tool_cls, attr)
    return None
