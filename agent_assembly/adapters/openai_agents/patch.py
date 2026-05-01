"""OpenAI Agents patch module."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
from dataclasses import dataclass
from functools import wraps
from typing import Any, Literal

from agent_assembly.adapters.crewai.patch import (
    _get_pending_tool_approval_timeout_seconds as _resolve_pending_timeout_seconds,
)
from agent_assembly.adapters.crewai.patch import (
    _normalize_decision as _normalize_governance_decision,
)

_ORIGINAL_FUNCTION_TOOL_CALL = "_agent_assembly_original_openai_agents_function_tool_call"
_PATCHED_FLAG = "_agent_assembly_openai_agents_function_tool_patched"
_PROCESS_AGENT_ID: str | None = None
_MAX_AUDIT_RESULT_CHARS = 2000


@dataclass(slots=True)
class OpenAIAgentsPatch:
    """Patch placeholder for OpenAI Agents SDK interception."""

    callback_handler: Any
    process_agent_id: str | None = None

    def apply(self) -> bool:
        set_process_agent_id(self.process_agent_id)
        function_tool_cls = _load_openai_agents_function_tool_class()
        if function_tool_cls is None:
            return False
        _apply_function_tool_call_patch(function_tool_cls, self.callback_handler)
        return True

    def revert(self) -> None:
        function_tool_cls = _load_openai_agents_function_tool_class()
        if function_tool_cls is not None:
            _revert_function_tool_call_patch(function_tool_cls)
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


def _resolve_agent_id(ctx: Any) -> str | None:
    candidate = getattr(ctx, "agent_id", None)
    if isinstance(candidate, str) and candidate:
        return candidate
    return _get_process_agent_id()


def _normalize_decision(
    decision: object,
) -> tuple[Literal["allow", "deny", "pending"], str | None]:
    return _normalize_governance_decision(decision)


def _resolve_governance_target(callback_handler: Any) -> Any:
    target = getattr(callback_handler, "_interceptor", None)
    if target is not None:
        return target
    return callback_handler


async def _invoke_async_tool_check(
    callback_handler: Any,
    *,
    tool_name: str,
    tool_input: Any,
    agent_id: str | None,
    ctx: Any,
) -> object:
    target = _resolve_governance_target(callback_handler)
    method = getattr(target, "check_tool_start", None)
    if not callable(method):
        return {"status": "allow"}

    result = method(
        serialized={"name": tool_name},
        input_str=str(tool_input),
        tool_name=tool_name,
        args=tool_input,
        agent_id=agent_id,
        run_context=ctx,
    )
    if inspect.isawaitable(result):
        return await result
    return result


def _get_pending_tool_approval_timeout_seconds(callback_handler: Any) -> int:
    return _resolve_pending_timeout_seconds(callback_handler)


async def _wait_for_async_tool_approval(
    callback_handler: Any,
    *,
    tool_name: str,
    timeout_seconds: int,
    tool_input: Any,
    agent_id: str | None,
    ctx: Any,
) -> object:
    target = _resolve_governance_target(callback_handler)
    method = getattr(target, "wait_for_tool_approval", None)
    if not callable(method):
        return {"status": "deny", "reason": "Approval handler is unavailable."}

    result = method(
        serialized={"name": tool_name},
        input_str=str(tool_input),
        tool_name=tool_name,
        timeout_seconds=timeout_seconds,
        args=tool_input,
        agent_id=agent_id,
        run_context=ctx,
    )
    if inspect.isawaitable(result):
        return await result
    return result


def _build_tool_result_error(
    *,
    tool_name: str,
    reason: str | None,
    is_pending_rejection: bool,
) -> object:
    try:
        module = importlib.import_module("openai.agents")
    except ImportError:
        module = None

    tool_result_cls = getattr(module, "ToolResult", None) if module is not None else None
    reason_text = reason or "No reason provided."
    if is_pending_rejection:
        error_message = f"Approval denied for tool '{tool_name}': {reason_text}"
    else:
        error_message = f"Action blocked by governance policy for tool '{tool_name}': {reason_text}"

    if isinstance(tool_result_cls, type):
        try:
            return tool_result_cls(error=error_message)
        except Exception:
            pass

    return {"error": error_message}


def _truncate_result_for_audit(result: object) -> str:
    return str(result)[:_MAX_AUDIT_RESULT_CHARS]


async def _record_async_tool_result(
    callback_handler: Any,
    *,
    tool_name: str,
    tool_input: Any,
    result: object,
    agent_id: str | None,
    ctx: Any,
) -> None:
    target = _resolve_governance_target(callback_handler)

    record_method = getattr(target, "record_result", None)
    if callable(record_method):
        recorded = record_method(
            tool_name=tool_name,
            args=tool_input,
            result=_truncate_result_for_audit(result),
            agent_id=agent_id,
            run_context=ctx,
        )
        if inspect.isawaitable(recorded):
            await recorded
        return None

    tool_end_method = getattr(target, "on_tool_end", None)
    if callable(tool_end_method):
        recorded = tool_end_method(
            output=_truncate_result_for_audit(result),
            tool_name=tool_name,
            agent_id=agent_id,
            run_context=ctx,
        )
        if inspect.isawaitable(recorded):
            await recorded


def _is_governance_error(error: Exception) -> bool:
    del error
    return True


def _apply_function_tool_call_patch(function_tool_cls: type[Any], callback_handler: Any) -> None:
    if getattr(function_tool_cls, _PATCHED_FLAG, False):
        return None

    original_call = getattr(function_tool_cls, "__call__", None)
    if not callable(original_call):
        return None

    @wraps(original_call)
    async def patched_call(self: Any, ctx: Any, tool_input: Any, *args: Any, **kwargs: Any) -> Any:
        tool_name = str(getattr(self, "name", self.__class__.__name__))
        agent_id = _resolve_agent_id(ctx)

        decision: object = {"status": "allow"}
        governance_failed = False
        try:
            decision = await _invoke_async_tool_check(
                callback_handler,
                tool_name=tool_name,
                tool_input=tool_input,
                agent_id=agent_id,
                ctx=ctx,
            )
            status, reason = _normalize_decision(decision)
            is_pending_flow = False
            if status == "pending":
                is_pending_flow = True
                timeout_seconds = _get_pending_tool_approval_timeout_seconds(callback_handler)
                final_decision = await _wait_for_async_tool_approval(
                    callback_handler,
                    tool_name=tool_name,
                    timeout_seconds=timeout_seconds,
                    tool_input=tool_input,
                    agent_id=agent_id,
                    ctx=ctx,
                )
                status, reason = _normalize_decision(final_decision)

            if status == "deny":
                blocked_result = _build_tool_result_error(
                    tool_name=tool_name,
                    reason=reason,
                    is_pending_rejection=is_pending_flow,
                )
                await _record_async_tool_result(
                    callback_handler,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    result=blocked_result,
                    agent_id=agent_id,
                    ctx=ctx,
                )
                return blocked_result
        except Exception as error:
            governance_failed = _is_governance_error(error)
            if not governance_failed:
                raise

        result = original_call(self, ctx, tool_input, *args, **kwargs)
        if inspect.isawaitable(result):
            result = await result

        if not governance_failed:
            await _record_async_tool_result(
                callback_handler,
                tool_name=tool_name,
                tool_input=tool_input,
                result=result,
                agent_id=agent_id,
                ctx=ctx,
            )
        return result

    setattr(function_tool_cls, _ORIGINAL_FUNCTION_TOOL_CALL, original_call)
    setattr(function_tool_cls, "__call__", patched_call)
    setattr(function_tool_cls, _PATCHED_FLAG, True)


def _revert_function_tool_call_patch(function_tool_cls: type[Any]) -> None:
    if not getattr(function_tool_cls, _PATCHED_FLAG, False):
        return None

    original_call = getattr(function_tool_cls, _ORIGINAL_FUNCTION_TOOL_CALL, None)
    if callable(original_call):
        setattr(function_tool_cls, "__call__", original_call)

    if hasattr(function_tool_cls, _ORIGINAL_FUNCTION_TOOL_CALL):
        delattr(function_tool_cls, _ORIGINAL_FUNCTION_TOOL_CALL)
    if hasattr(function_tool_cls, _PATCHED_FLAG):
        delattr(function_tool_cls, _PATCHED_FLAG)
