"""Microsoft Agent Framework patch module.

The interception point is ``agent_framework.FunctionTool.invoke`` — the single
async coroutine through which **every** function tool executes. Both the
``@agent_framework.tool`` decorator and direct ``FunctionTool(...)`` construction
produce ``FunctionTool`` instances, and agents/workflows dispatch tool calls
through ``FunctionTool.invoke``. Patching that one method therefore governs all
tool execution without requiring the user to register any framework middleware
(which would be opt-in and bypassable).

Governance contract (mirrors the CrewAI / Pydantic AI adapters):

- A ``deny`` verdict raises ``PolicyViolationError`` *before* the wrapped
  function runs, so a denied tool never executes its side effects.
- A ``pending`` verdict waits for an approval decision and then allows or denies.
- An ``allow`` verdict runs the original ``invoke`` and records the result.
- Under ``enforce`` posture an unknown / malformed verdict fails closed (deny);
  under ``observe`` / ``disabled`` it fails open (allow).
"""

from __future__ import annotations

import importlib as importlib
import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING, Any, Literal

from agent_assembly.adapters._shared.audit_record import arecord_denied_tool_result
from agent_assembly.adapters.crewai.patch import (
    _get_pending_tool_approval_timeout_seconds as _resolve_pending_timeout_seconds,
)
from agent_assembly.adapters.crewai.patch import (
    _interceptor_enforces,
    _missing_interceptor_decision,
)
from agent_assembly.adapters.crewai.patch import (
    _normalize_decision as _normalize_governance_decision,
)
from agent_assembly.core.spawn import _SPAWN_CTX, SpawnContext, spawn_context_scope

if TYPE_CHECKING:
    from agent_assembly.exceptions import PolicyViolationError

_ORIGINAL_FUNCTION_TOOL_INVOKE = "_agent_assembly_original_maf_function_tool_invoke"
_TOOLS_PATCHED_FLAG = "_agent_assembly_maf_function_tool_patched"
_PROCESS_AGENT_ID: str | None = None
_MAX_AUDIT_RESULT_CHARS = 2000


@dataclass(slots=True)
class MicrosoftAgentFrameworkPatch:
    """Applies Microsoft Agent Framework runtime monkey-patching hooks."""

    callback_handler: Any
    process_agent_id: str | None = None

    def apply(self) -> bool:
        """Patch ``FunctionTool.invoke`` and return whether a hook was installed.

        Returns ``False`` (a no-op) when ``agent_framework`` is not importable or
        does not expose a callable ``FunctionTool.invoke``, rather than raising.
        """
        set_process_agent_id(self.process_agent_id)

        function_tool_cls = _load_function_tool_class()
        if function_tool_cls is None:
            set_process_agent_id(None)
            return False

        return _apply_function_tool_invoke_patch(function_tool_cls, self.callback_handler)

    def revert(self) -> None:
        """Revert the ``FunctionTool.invoke`` patch when available."""
        function_tool_cls = _load_function_tool_class()
        if function_tool_cls is not None:
            _revert_function_tool_invoke_patch(function_tool_cls)
        set_process_agent_id(None)
        return None


def _load_function_tool_class() -> type[Any] | None:
    try:
        module = importlib.import_module("agent_framework")
    except ImportError:
        return None

    function_tool_cls = getattr(module, "FunctionTool", None)
    if isinstance(function_tool_cls, type):
        return function_tool_cls
    return None


def set_process_agent_id(agent_id: str | None) -> None:
    global _PROCESS_AGENT_ID
    _PROCESS_AGENT_ID = agent_id


def _get_process_agent_id() -> str | None:
    if isinstance(_PROCESS_AGENT_ID, str) and _PROCESS_AGENT_ID:
        return _PROCESS_AGENT_ID
    return None


def _coerce_args_mapping(value: Any) -> dict[str, Any] | None:
    """Return a plain dict for a Pydantic model / mapping argument, else ``None``."""
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, Mapping):
            return dict(dumped)

    if isinstance(value, Mapping):
        return dict(value)

    return None


def _serialize_tool_args(
    arguments: Any,
    context: Any,
    direct_kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Collapse the several ``FunctionTool.invoke`` argument channels into one dict.

    ``invoke`` accepts arguments via ``arguments=`` (a Pydantic model or mapping),
    via ``context.arguments``, or as direct keyword arguments. The governance
    check needs a single ``dict`` view of the call's inputs regardless of which
    channel the caller used.
    """
    mapped = _coerce_args_mapping(arguments)
    if mapped is not None:
        return mapped

    if context is not None:
        mapped = _coerce_args_mapping(getattr(context, "arguments", None))
        if mapped is not None:
            return mapped

    if direct_kwargs:
        return dict(direct_kwargs)

    if arguments is not None:
        return {"value": str(arguments)}

    return {}


def _resolve_agent_id(context: Any) -> str | None:
    if context is not None:
        for attr in ("agent_id", "assembly_agent_id"):
            candidate = getattr(context, attr, None)
            if isinstance(candidate, str) and candidate:
                return candidate
    return _get_process_agent_id()


def _current_spawn_depth() -> int:
    current = _SPAWN_CTX.get()
    return (current.depth + 1) if current is not None else 1


def _normalize_decision(
    decision: object,
    *,
    enforce: bool = False,
) -> tuple[Literal["allow", "deny", "pending"], str | None]:
    return _normalize_governance_decision(decision, enforce=enforce)


def _get_pending_tool_approval_timeout_seconds(callback_handler: Any) -> int:
    return _resolve_pending_timeout_seconds(callback_handler)


def _build_denied_error(tool_name: str, reason: str | None) -> PolicyViolationError:
    from agent_assembly.exceptions import PolicyViolationError

    reason_text = reason or "No reason provided."
    return PolicyViolationError(f"Tool '{tool_name}' blocked by governance policy: {reason_text}")


def _build_pending_rejected_error(tool_name: str, reason: str | None) -> PolicyViolationError:
    from agent_assembly.exceptions import PolicyViolationError

    reason_text = reason or "No reason provided."
    return PolicyViolationError(f"Tool '{tool_name}' rejected during approval: {reason_text}")


async def _invoke_async_tool_check(
    callback_handler: Any,
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    agent_id: str | None,
) -> object:
    method = getattr(callback_handler, "check_tool_start", None)
    if not callable(method):
        return _missing_interceptor_decision(callback_handler)

    result = method(
        serialized={"name": tool_name},
        input_str=str(tool_args),
        tool_name=tool_name,
        args=tool_args,
        agent_id=agent_id,
    )
    if inspect.isawaitable(result):
        return await result
    return result


async def _wait_for_async_tool_approval(
    callback_handler: Any,
    *,
    tool_name: str,
    timeout_seconds: int,
    tool_args: dict[str, Any],
    agent_id: str | None,
) -> object:
    method = getattr(callback_handler, "wait_for_tool_approval", None)
    if not callable(method):
        return {"status": "deny", "reason": "Approval handler is unavailable."}

    result = method(
        serialized={"name": tool_name},
        input_str=str(tool_args),
        tool_name=tool_name,
        timeout_seconds=timeout_seconds,
        args=tool_args,
        agent_id=agent_id,
    )
    if inspect.isawaitable(result):
        return await result
    return result


def _truncate_result_for_audit(result: object) -> str:
    return str(result)[:_MAX_AUDIT_RESULT_CHARS]


async def _record_async_tool_result(
    callback_handler: Any,
    *,
    tool_name: str,
    result: object,
    agent_id: str | None,
) -> None:
    record_method = getattr(callback_handler, "record_result", None)
    if callable(record_method):
        recorded = record_method(
            tool_name=tool_name,
            result=_truncate_result_for_audit(result),
            agent_id=agent_id,
        )
        if inspect.isawaitable(recorded):
            await recorded
        return None

    tool_end_method = getattr(callback_handler, "on_tool_end", None)
    if callable(tool_end_method):
        recorded = tool_end_method(
            output=_truncate_result_for_audit(result),
            tool_name=tool_name,
            agent_id=agent_id,
        )
        if inspect.isawaitable(recorded):
            await recorded
    return None


def _recover_invoke_call_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[Any, Any, dict[str, Any]]:
    """Recover ``(arguments, context, direct_kwargs)`` of a Microsoft Agent
    Framework ``FunctionTool.invoke`` call.

    ``invoke`` may be called positionally (arguments, then context); fall back to
    the positional slots so content policy still inspects the argument values
    instead of an empty mapping (AAASM-4848). ``direct_kwargs`` are the extras the
    framework forwards straight to the wrapped function (i.e. not the reserved
    invoke parameters).
    """
    arguments = kwargs.get("arguments")
    if arguments is None and args:
        arguments = args[0]
    context = kwargs.get("context")
    if context is None and len(args) >= 2:
        context = args[1]
    direct_kwargs = {
        key: value
        for key, value in kwargs.items()
        if key not in ("arguments", "context", "tool_call_id", "skip_parsing")
    }
    return arguments, context, direct_kwargs


def _apply_function_tool_invoke_patch(function_tool_cls: type[Any], callback_handler: Any) -> bool:
    if vars(function_tool_cls).get(_TOOLS_PATCHED_FLAG, False):
        return True

    original_invoke = getattr(function_tool_cls, "invoke", None)
    if not callable(original_invoke):
        return False

    enforce = _interceptor_enforces(callback_handler)

    @wraps(original_invoke)
    async def patched_invoke(self: Any, *args: Any, **kwargs: Any) -> Any:
        tool_name = str(getattr(self, "name", self.__class__.__name__))
        arguments, context, direct_kwargs = _recover_invoke_call_args(args, kwargs)
        tool_args = _serialize_tool_args(arguments, context, direct_kwargs)
        agent_id = _resolve_agent_id(context)

        decision = await _invoke_async_tool_check(
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
            final_decision = await _wait_for_async_tool_approval(
                callback_handler,
                tool_name=tool_name,
                timeout_seconds=timeout_seconds,
                tool_args=tool_args,
                agent_id=agent_id,
            )
            status, reason = _normalize_decision(final_decision, enforce=enforce)

        # Fail closed: only an explicit "allow" may proceed. A terminal "pending"
        # (approval timed out or the resolver returned pending again) is a
        # non-decision, not a grant — blocking it here stops it from falling
        # through and running the tool, matching the LangChain handler.
        if status != "allow":
            error = (
                _build_pending_rejected_error(tool_name, reason)
                if is_pending_flow
                else _build_denied_error(tool_name, reason)
            )
            # AAASM-5787: the deny used to raise straight past the record call
            # below, so this adapter built nothing for the sink to forward.
            await arecord_denied_tool_result(
                callback_handler, tool_name=tool_name, result=str(error), agent_id=agent_id
            )
            raise error

        spawn_ctx = SpawnContext(
            parent_agent_id=agent_id or "",
            depth=_current_spawn_depth(),
            spawned_by_tool=tool_name,
            delegation_reason=f"tool:{tool_name}",
        )
        with spawn_context_scope(spawn_ctx):
            result = await original_invoke(self, *args, **kwargs)

        await _record_async_tool_result(
            callback_handler,
            tool_name=tool_name,
            result=result,
            agent_id=agent_id,
        )
        return result

    setattr(function_tool_cls, _ORIGINAL_FUNCTION_TOOL_INVOKE, original_invoke)
    function_tool_cls.invoke = patched_invoke
    setattr(function_tool_cls, _TOOLS_PATCHED_FLAG, True)
    return True


def _revert_function_tool_invoke_patch(function_tool_cls: type[Any]) -> None:
    if not vars(function_tool_cls).get(_TOOLS_PATCHED_FLAG, False):
        return None

    original_invoke = vars(function_tool_cls).get(_ORIGINAL_FUNCTION_TOOL_INVOKE, None)
    if callable(original_invoke):
        function_tool_cls.invoke = original_invoke

    if _ORIGINAL_FUNCTION_TOOL_INVOKE in vars(function_tool_cls):
        delattr(function_tool_cls, _ORIGINAL_FUNCTION_TOOL_INVOKE)
    if _TOOLS_PATCHED_FLAG in vars(function_tool_cls):
        delattr(function_tool_cls, _TOOLS_PATCHED_FLAG)
    return None
