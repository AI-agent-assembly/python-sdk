"""Pydantic AI patch module."""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
import importlib
import inspect
from typing import Any, Literal, Mapping

_ORIGINAL_TOOL_RUN = "_agent_assembly_original_pydantic_ai_tool_run"
_TOOLS_PATCHED_FLAG = "_agent_assembly_pydantic_ai_tools_patched"
_PROCESS_AGENT_ID: str | None = None
_DEFAULT_PENDING_APPROVAL_TIMEOUT_SECONDS = 300
_MAX_AUDIT_RESULT_CHARS = 2000


@dataclass(slots=True)
class PydanticAIPatch:
    """Applies Pydantic AI runtime monkey-patching hooks."""

    callback_handler: Any

    def apply(self) -> bool:
        """Apply patch wiring and return whether Pydantic AI is available."""
        tool_cls = _load_pydantic_ai_tool_class()
        if tool_cls is None:
            return False
        _apply_tool_run_patch(tool_cls, self.callback_handler)
        return True


class AssemblyModelWrapper:
    """Optional model wrapper for LLM input scan-forward interception."""

    def __init__(self, model: Any, callback_handler: Any) -> None:
        self._model = model
        self._callback_handler = callback_handler

    async def request(self, *args: Any, **kwargs: Any) -> Any:
        scan_method = getattr(self._callback_handler, "on_llm_start_scan", None)
        if callable(scan_method):
            scan_result = scan_method(
                serialized={"name": self._model.__class__.__name__},
                prompts=[str(args[0])] if args else [],
                run_id=kwargs.get("run_id"),
            )
            if inspect.isawaitable(scan_result):
                await scan_result

        result = self._model.request(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._model, name)


def _load_pydantic_ai_tool_class() -> type[Any] | None:
    try:
        module = importlib.import_module("pydantic_ai.tools")
    except ImportError:
        return None

    tool_cls = getattr(module, "Tool", None)
    if isinstance(tool_cls, type):
        return tool_cls
    return None


def _apply_tool_run_patch(tool_cls: type[Any], callback_handler: Any) -> None:
    if getattr(tool_cls, _TOOLS_PATCHED_FLAG, False):
        return None

    original_run = tool_cls._run

    @wraps(original_run)
    async def patched_run(self: Any, ctx: Any, args: Any, **kwargs: Any) -> Any:
        tool_name = str(getattr(self, "name", self.__class__.__name__))
        tool_args = _serialize_tool_args(args)
        agent_id = _resolve_agent_id(ctx)
        run_id = _resolve_run_id(ctx)

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

        result = original_run(self, ctx, args, **kwargs)
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

    setattr(tool_cls, _ORIGINAL_TOOL_RUN, original_run)
    setattr(tool_cls, "_run", patched_run)
    setattr(tool_cls, _TOOLS_PATCHED_FLAG, True)


def set_process_agent_id(agent_id: str | None) -> None:
    global _PROCESS_AGENT_ID
    _PROCESS_AGENT_ID = agent_id


def _get_process_agent_id() -> str | None:
    if isinstance(_PROCESS_AGENT_ID, str) and _PROCESS_AGENT_ID:
        return _PROCESS_AGENT_ID
    return None


def _resolve_agent_id(ctx: Any) -> str | None:
    deps = getattr(ctx, "deps", None)
    candidate = getattr(deps, "assembly_agent_id", None)
    if isinstance(candidate, str) and candidate:
        return candidate
    return _get_process_agent_id()


def _resolve_run_id(ctx: Any) -> str | None:
    run_id = getattr(ctx, "run_id", None)
    if run_id is None:
        return None
    return str(run_id)


def _serialize_tool_args(args: Any) -> dict[str, Any]:
    if hasattr(args, "model_dump"):
        model_dump = getattr(args, "model_dump")
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
    if isinstance(decision, str):
        normalized = decision.strip().lower()
        if normalized == "deny":
            return "deny", None
        if normalized == "pending":
            return "pending", None
        return "allow", None

    if isinstance(decision, Mapping):
        raw_status = str(decision.get("status", "allow")).strip().lower()
        if raw_status == "deny":
            status: Literal["allow", "deny", "pending"] = "deny"
        elif raw_status == "pending":
            status = "pending"
        else:
            status = "allow"

        reason_value = decision.get("reason")
        reason = str(reason_value) if reason_value is not None else None
        return status, reason

    return "allow", None


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
    provider = getattr(callback_handler, "get_pending_tool_approval_timeout_seconds", None)
    if callable(provider):
        configured = provider()
    else:
        configured = getattr(callback_handler, "pending_tool_approval_timeout_seconds", None)

    if isinstance(configured, str):
        stripped = configured.strip()
        if stripped.isdigit():
            parsed = int(stripped)
            if parsed > 0:
                return parsed
        return _DEFAULT_PENDING_APPROVAL_TIMEOUT_SECONDS

    if isinstance(configured, bool):
        return _DEFAULT_PENDING_APPROVAL_TIMEOUT_SECONDS

    if isinstance(configured, int) and configured > 0:
        return configured

    return _DEFAULT_PENDING_APPROVAL_TIMEOUT_SECONDS


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
