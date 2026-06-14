"""Google ADK patch module."""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from functools import wraps
from typing import Any, Literal

from agent_assembly.adapters.crewai.patch import (
    _get_pending_tool_approval_timeout_seconds as _resolve_pending_timeout_seconds,
)
from agent_assembly.adapters.crewai.patch import (
    _normalize_decision as _normalize_governance_decision,
)
from agent_assembly.core.spawn import _SPAWN_CTX, SpawnContext, spawn_context_scope

_ORIGINAL_TOOL_RUN_ASYNC = "_agent_assembly_original_google_adk_tool_run_async"
_TOOLS_PATCHED_FLAG = "_agent_assembly_google_adk_tools_patched"
_ORIGINAL_AGENT_RUN_ASYNC = "_agent_assembly_original_google_adk_agent_run_async"
_AGENT_PATCHED_FLAG = "_agent_assembly_google_adk_agent_patched"
_PROCESS_AGENT_ID: str | None = None
_MAX_AUDIT_RESULT_CHARS = 2000


@dataclass(slots=True)
class GoogleADKPatch:
    """Applies Google ADK runtime monkey-patching hooks."""

    callback_handler: Any
    process_agent_id: str | None = None

    def apply(self) -> bool:
        """Apply patch wiring and return whether Google ADK is available.

        Patches ``BaseTool.run_async`` and every concrete tool class that
        overrides ``run_async`` (e.g. ``FunctionTool``), so interception still
        runs for ADK 1.x tools whose subclass shadows the base method.
        """
        set_process_agent_id(self.process_agent_id)
        tool_cls = _load_google_adk_base_tool_class()
        if tool_cls is None:
            return False
        _apply_tool_run_async_patch(tool_cls, self.callback_handler)
        for concrete_cls in _load_google_adk_concrete_tool_classes(tool_cls):
            _apply_tool_run_async_patch(concrete_cls, self.callback_handler)
        agent_cls = _load_google_adk_base_agent_class()
        if agent_cls is not None:
            _apply_agent_run_async_patch(agent_cls, self.process_agent_id)
        return True

    def revert(self) -> None:
        """Revert Google ADK tool and agent patches when available."""
        agent_cls = _load_google_adk_base_agent_class()
        if agent_cls is not None:
            _revert_agent_run_async_patch(agent_cls)
        tool_cls = _load_google_adk_base_tool_class()
        if tool_cls is not None:
            for concrete_cls in _load_google_adk_concrete_tool_classes(tool_cls):
                _revert_tool_run_async_patch(concrete_cls)
            _revert_tool_run_async_patch(tool_cls)
        set_process_agent_id(None)
        return None


def _load_google_adk_base_tool_class() -> type[Any] | None:
    try:
        module = importlib.import_module("google.adk.tools")
    except ImportError:
        return None

    tool_cls = getattr(module, "BaseTool", None)
    if isinstance(tool_cls, type):
        return tool_cls
    return None


def _load_google_adk_concrete_tool_classes(base_tool_cls: type[Any]) -> list[type[Any]]:
    """Return concrete ADK tool classes that OVERRIDE ``run_async``.

    Concrete ADK 1.x tools (e.g. ``FunctionTool``) define their own
    ``run_async`` on the subclass, so a patch on ``BaseTool.run_async`` never
    runs for them. Discover such classes in ``google.adk.tools`` so they can be
    patched directly.
    """
    try:
        module = importlib.import_module("google.adk.tools")
    except ImportError:
        return []

    concrete: list[type[Any]] = []
    for attr_value in vars(module).values():
        if not isinstance(attr_value, type):
            continue
        if attr_value is base_tool_cls:
            continue
        if not issubclass(attr_value, base_tool_cls):
            continue
        if "run_async" in vars(attr_value):
            concrete.append(attr_value)
    return concrete


def _load_google_adk_base_agent_class() -> type[Any] | None:
    try:
        module = importlib.import_module("google.adk.agents")
    except ImportError:
        return None

    agent_cls = getattr(module, "BaseAgent", None)
    if isinstance(agent_cls, type):
        return agent_cls
    return None


def _current_spawn_depth() -> int:
    current = _SPAWN_CTX.get()
    return (current.depth + 1) if current is not None else 1


def _apply_agent_run_async_patch(agent_cls: type[Any], process_agent_id: str | None) -> None:
    if getattr(agent_cls, _AGENT_PATCHED_FLAG, False):
        return None

    original_run_async = agent_cls.run_async

    @wraps(original_run_async)
    async def patched_run_async(self: Any, *args: Any, **kwargs: Any) -> Any:
        spawn_ctx = SpawnContext(
            parent_agent_id=process_agent_id or "",
            depth=_current_spawn_depth(),
            spawned_by_tool="google_adk_agent",
        )
        with spawn_context_scope(spawn_ctx):
            async for event in original_run_async(self, *args, **kwargs):
                yield event

    setattr(agent_cls, _ORIGINAL_AGENT_RUN_ASYNC, original_run_async)
    agent_cls.run_async = patched_run_async
    setattr(agent_cls, _AGENT_PATCHED_FLAG, True)
    return None


def _revert_agent_run_async_patch(agent_cls: type[Any]) -> None:
    if not getattr(agent_cls, _AGENT_PATCHED_FLAG, False):
        return None

    original_run_async = getattr(agent_cls, _ORIGINAL_AGENT_RUN_ASYNC, None)
    if callable(original_run_async):
        agent_cls.run_async = original_run_async

    if hasattr(agent_cls, _ORIGINAL_AGENT_RUN_ASYNC):
        delattr(agent_cls, _ORIGINAL_AGENT_RUN_ASYNC)
    if hasattr(agent_cls, _AGENT_PATCHED_FLAG):
        delattr(agent_cls, _AGENT_PATCHED_FLAG)
    return None


def _apply_tool_run_async_patch(tool_cls: type[Any], callback_handler: Any) -> None:
    # Check the class's OWN dict, not inherited state — a concrete subclass that
    # overrides run_async must be patched even when its base is already patched.
    if vars(tool_cls).get(_TOOLS_PATCHED_FLAG, False):
        return None

    original_run_async = tool_cls.run_async

    @wraps(original_run_async)
    async def patched_run_async(self: Any, *, args: Any, tool_context: Any, **kwargs: Any) -> Any:
        tool_name = str(getattr(self, "name", self.__class__.__name__))
        tool_args = _serialize_tool_args(args)
        agent_id = _resolve_agent_id(tool_context)
        run_id = _resolve_run_id(tool_context)

        decision = await _invoke_async_tool_check(
            callback_handler,
            tool_name=tool_name,
            tool_args=tool_args,
            agent_id=agent_id,
            run_id=run_id,
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
                tool_args=tool_args,
                agent_id=agent_id,
                run_id=run_id,
            )
            status, reason = _normalize_decision(final_decision)

        if status == "deny":
            if is_pending_flow:
                raise _build_pending_rejected_error(tool_name, reason)
            raise _build_denied_error(tool_name, reason)

        spawn_ctx = SpawnContext(
            parent_agent_id=agent_id or "",
            depth=_current_spawn_depth(),
            spawned_by_tool=tool_name,
            delegation_reason=f"tool:{tool_name}",
        )
        with spawn_context_scope(spawn_ctx):
            result = original_run_async(self, args=args, tool_context=tool_context, **kwargs)
            if inspect.isawaitable(result):
                result = await result

        await _record_async_tool_result(
            callback_handler,
            tool_name=tool_name,
            result=result,
            agent_id=agent_id,
            run_id=run_id,
        )
        return result

    setattr(tool_cls, _ORIGINAL_TOOL_RUN_ASYNC, original_run_async)
    tool_cls.run_async = patched_run_async
    setattr(tool_cls, _TOOLS_PATCHED_FLAG, True)
    return None


def _revert_tool_run_async_patch(tool_cls: type[Any]) -> None:
    # Inspect OWN dict so reverting one class never acts on inherited state.
    if not vars(tool_cls).get(_TOOLS_PATCHED_FLAG, False):
        return None

    original_run_async = vars(tool_cls).get(_ORIGINAL_TOOL_RUN_ASYNC)
    if callable(original_run_async):
        tool_cls.run_async = original_run_async

    if _ORIGINAL_TOOL_RUN_ASYNC in vars(tool_cls):
        delattr(tool_cls, _ORIGINAL_TOOL_RUN_ASYNC)
    if _TOOLS_PATCHED_FLAG in vars(tool_cls):
        delattr(tool_cls, _TOOLS_PATCHED_FLAG)
    return None


def set_process_agent_id(agent_id: str | None) -> None:
    global _PROCESS_AGENT_ID
    _PROCESS_AGENT_ID = agent_id


def _get_process_agent_id() -> str | None:
    if isinstance(_PROCESS_AGENT_ID, str) and _PROCESS_AGENT_ID:
        return _PROCESS_AGENT_ID
    return None


def _resolve_agent_id(tool_context: Any) -> str | None:
    invocation_context = getattr(tool_context, "invocation_context", None)
    candidate = getattr(invocation_context, "assembly_agent_id", None)
    if isinstance(candidate, str) and candidate:
        return candidate
    return _get_process_agent_id()


def _resolve_run_id(tool_context: Any) -> str | None:
    invocation_context = getattr(tool_context, "invocation_context", None)
    invocation_id = getattr(invocation_context, "invocation_id", None)
    if invocation_id is None:
        return None
    return str(invocation_id)


def _serialize_tool_args(args: Any) -> dict[str, Any]:
    if hasattr(args, "model_dump"):
        model_dump = args.model_dump
        if callable(model_dump):
            dumped = model_dump()
            if isinstance(dumped, dict):
                return dict(dumped)

    if isinstance(args, Mapping):
        return dict(args)

    return {"value": str(args)}


def _normalize_decision(
    decision: object,
) -> tuple[Literal["allow", "deny", "pending"], str | None]:
    return _normalize_governance_decision(decision)


async def _invoke_async_tool_check(
    callback_handler: Any,
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    agent_id: str | None,
    run_id: str | None,
) -> object:
    method = getattr(callback_handler, "check_tool_start", None)
    if not callable(method):
        return {"status": "allow"}

    result = method(
        serialized={"name": tool_name},
        input_str=str(tool_args),
        tool_name=tool_name,
        args=tool_args,
        agent_id=agent_id,
        run_id=run_id,
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
    run_id: str | None,
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
        run_id=run_id,
    )
    if inspect.isawaitable(result):
        return await result
    return result


def _get_pending_tool_approval_timeout_seconds(callback_handler: Any) -> int:
    return _resolve_pending_timeout_seconds(callback_handler)


def _truncate_result_for_audit(result: object) -> str:
    return str(result)[:_MAX_AUDIT_RESULT_CHARS]


async def _record_async_tool_result(
    callback_handler: Any,
    *,
    tool_name: str,
    result: object,
    agent_id: str | None,
    run_id: str | None,
) -> None:
    record_method = getattr(callback_handler, "record_result", None)
    if callable(record_method):
        recorded = record_method(
            tool_name=tool_name,
            result=_truncate_result_for_audit(result),
            agent_id=agent_id,
            run_id=run_id,
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
            run_id=run_id,
        )
        if inspect.isawaitable(recorded):
            await recorded


def _build_denied_error(tool_name: str, reason: str | None) -> Exception:
    from agent_assembly.exceptions import PolicyViolationError

    reason_text = reason or "No reason provided."
    return PolicyViolationError(f"Tool '{tool_name}' blocked by governance policy: {reason_text}")


def _build_pending_rejected_error(tool_name: str, reason: str | None) -> Exception:
    from agent_assembly.exceptions import PolicyViolationError

    reason_text = reason or "No reason provided."
    return PolicyViolationError(f"Tool '{tool_name}' rejected during approval: {reason_text}")
