"""OpenAI Agents patch module."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Literal

from agent_assembly.adapters.crewai.patch import (
    _get_pending_tool_approval_timeout_seconds as _resolve_pending_timeout_seconds,
)
from agent_assembly.adapters.crewai.patch import (
    _normalize_decision as _normalize_governance_decision,
)
from agent_assembly.core.spawn import _SPAWN_CTX, SpawnContext, spawn_context_scope

_ORIGINAL_FUNCTION_TOOL_CALL = "_agent_assembly_original_openai_agents_function_tool_call"
_PATCHED_FLAG = "_agent_assembly_openai_agents_function_tool_patched"
_ORIGINAL_RUNNER_RUN = "_agent_assembly_original_openai_agents_runner_run"
_RUNNER_PATCHED_FLAG = "_agent_assembly_openai_agents_runner_patched"
_ORIGINAL_HANDOFF_CALL = "_agent_assembly_original_openai_agents_handoff_call"
_HANDOFF_PATCHED_FLAG = "_agent_assembly_openai_agents_handoff_patched"
_PROCESS_AGENT_ID: str | None = None
_EDGE_EMITTER: Any = None
_MAX_AUDIT_RESULT_CHARS = 2000
_MAX_DELEGATION_REASON_CHARS = 256


def set_edge_emitter(emitter: Any) -> None:
    """Register the EdgeEmitter used for fire-and-forget topology edge reporting."""
    global _EDGE_EMITTER
    _EDGE_EMITTER = emitter


@dataclass(slots=True)
class OpenAIAgentsPatch:
    """Patch placeholder for OpenAI Agents SDK interception."""

    callback_handler: Any
    process_agent_id: str | None = None
    edge_emitter: Any = field(default=None)

    def apply(self) -> bool:
        set_process_agent_id(self.process_agent_id)
        if self.edge_emitter is not None:
            set_edge_emitter(self.edge_emitter)
        function_tool_cls = _load_openai_agents_function_tool_class()
        if function_tool_cls is None:
            return False
        _apply_function_tool_call_patch(function_tool_cls, self.callback_handler)
        runner_cls = _load_openai_agents_runner_class()
        if runner_cls is not None:
            _apply_runner_run_patch(runner_cls, self.process_agent_id)
        handoff_cls = _load_openai_agents_handoff_class()
        if handoff_cls is not None:
            _apply_handoff_call_patch(handoff_cls, self.process_agent_id)
        return True

    def revert(self) -> None:
        handoff_cls = _load_openai_agents_handoff_class()
        if handoff_cls is not None:
            _revert_handoff_call_patch(handoff_cls)
        runner_cls = _load_openai_agents_runner_class()
        if runner_cls is not None:
            _revert_runner_run_patch(runner_cls)
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


def _load_openai_agents_runner_class() -> type[Any] | None:
    try:
        module = importlib.import_module("openai.agents")
    except ImportError:
        return None
    runner_cls = getattr(module, "Runner", None)
    if isinstance(runner_cls, type):
        return runner_cls
    return None


def _load_openai_agents_handoff_class() -> type[Any] | None:
    try:
        module = importlib.import_module("openai.agents")
    except ImportError:
        return None
    handoff_cls = getattr(module, "Handoff", None)
    if isinstance(handoff_cls, type):
        return handoff_cls
    return None


def _extract_handoff_delegation_reason(handoff_obj: Any) -> str:
    for attr in ("tool_description", "description", "reason"):
        value = getattr(handoff_obj, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()[:_MAX_DELEGATION_REASON_CHARS]
    return "handoff"


def _apply_handoff_call_patch(handoff_cls: type[Any], process_agent_id: str | None) -> None:
    if getattr(handoff_cls, _HANDOFF_PATCHED_FLAG, False):
        return None

    if not callable(handoff_cls):
        return None
    original_call = handoff_cls.__call__

    @wraps(original_call)
    async def patched_call(self: Any, *args: Any, **kwargs: Any) -> Any:
        spawn_ctx = SpawnContext(
            parent_agent_id=process_agent_id or "",
            depth=_current_spawn_depth(),
            spawned_by_tool=None,
            delegation_reason=_extract_handoff_delegation_reason(self),
        )
        with spawn_context_scope(spawn_ctx):
            result = original_call(self, *args, **kwargs)
            if inspect.isawaitable(result):
                result = await result

        # Emit a DelegatesTo edge from the delegating agent to the handoff target.
        if _EDGE_EMITTER is not None and process_agent_id:
            target_id = getattr(self, "agent_name", None) or getattr(self, "name", None) or "unknown"
            emit = getattr(_EDGE_EMITTER, "emit", None)
            if callable(emit):
                reason = _extract_handoff_delegation_reason(self)
                emit(process_agent_id, str(target_id), "delegates_to", {"reason": reason})

        return result

    setattr(handoff_cls, _ORIGINAL_HANDOFF_CALL, original_call)
    handoff_cls.__call__ = patched_call
    setattr(handoff_cls, _HANDOFF_PATCHED_FLAG, True)
    return None


def _revert_handoff_call_patch(handoff_cls: type[Any]) -> None:
    if not getattr(handoff_cls, _HANDOFF_PATCHED_FLAG, False):
        return None
    original_call = getattr(handoff_cls, _ORIGINAL_HANDOFF_CALL, None)
    if callable(original_call):
        handoff_cls.__call__ = original_call
    for attr in (_ORIGINAL_HANDOFF_CALL, _HANDOFF_PATCHED_FLAG):
        if hasattr(handoff_cls, attr):
            delattr(handoff_cls, attr)
    return None


def _current_spawn_depth() -> int:
    current = _SPAWN_CTX.get()
    return (current.depth + 1) if current is not None else 1


def _call_original_run(
    runner_cls: type[Any],
    original_run: Any,
    agent: Any,
    input: Any,
    kwargs: dict[str, Any],
) -> Any:
    """Invoke original_run correctly regardless of whether its __func__ declares cls."""
    func = getattr(original_run, "__func__", None)
    if func is None:
        # Not a classmethod descriptor — call directly.
        return original_run(agent, input=input, **kwargs)
    params = list(inspect.signature(func).parameters.keys())
    if params and params[0] in ("cls", "klass", "mcs"):
        # Real classmethod: __func__(cls, agent, input=...)
        return func(runner_cls, agent, input=input, **kwargs)
    # Test-style function used as classmethod without cls param.
    return func(agent, input=input, **kwargs)


def _apply_runner_run_patch(runner_cls: type[Any], process_agent_id: str | None) -> None:
    if getattr(runner_cls, _RUNNER_PATCHED_FLAG, False):
        return None

    # Capture the bound method descriptor before patching.
    original_run = runner_cls.run

    @wraps(original_run)
    async def patched_run(agent: Any, *, input: Any, **kwargs: Any) -> Any:
        spawn_ctx = SpawnContext(
            parent_agent_id=process_agent_id or "",
            depth=_current_spawn_depth(),
            spawned_by_tool="openai_agents_runner",
        )
        with spawn_context_scope(spawn_ctx):
            result = _call_original_run(runner_cls, original_run, agent, input, kwargs)
            if inspect.isawaitable(result):
                return await result
            return result

    # Store the original bound method for revert.  Set patched_run as a plain
    # function — when called as Runner.run(agent, input=...) Python does not
    # inject cls, so the signature (agent, *, input, **kwargs) is correct.
    setattr(runner_cls, _ORIGINAL_RUNNER_RUN, original_run)
    runner_cls.run = patched_run
    setattr(runner_cls, _RUNNER_PATCHED_FLAG, True)
    return None


def _revert_runner_run_patch(runner_cls: type[Any]) -> None:
    if not getattr(runner_cls, _RUNNER_PATCHED_FLAG, False):
        return None
    original_run = getattr(runner_cls, _ORIGINAL_RUNNER_RUN, None)
    if callable(original_run):
        runner_cls.run = original_run
    for attr in (_ORIGINAL_RUNNER_RUN, _RUNNER_PATCHED_FLAG):
        if hasattr(runner_cls, attr):
            delattr(runner_cls, attr)
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

    if not callable(function_tool_cls):
        return None
    original_call = function_tool_cls.__call__

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
    function_tool_cls.__call__ = patched_call
    setattr(function_tool_cls, _PATCHED_FLAG, True)


def _revert_function_tool_call_patch(function_tool_cls: type[Any]) -> None:
    if not getattr(function_tool_cls, _PATCHED_FLAG, False):
        return None

    original_call = getattr(function_tool_cls, _ORIGINAL_FUNCTION_TOOL_CALL, None)
    if callable(original_call):
        function_tool_cls.__call__ = original_call

    if hasattr(function_tool_cls, _ORIGINAL_FUNCTION_TOOL_CALL):
        delattr(function_tool_cls, _ORIGINAL_FUNCTION_TOOL_CALL)
    if hasattr(function_tool_cls, _PATCHED_FLAG):
        delattr(function_tool_cls, _PATCHED_FLAG)
