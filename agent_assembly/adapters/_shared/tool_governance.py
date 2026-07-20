"""Shared async tool-governance flow for framework adapters.

The Google ADK and Pydantic AI adapters intercept tool execution through
framework-specific hook points, but the governance logic they run once a tool
call is intercepted is identical: serialize the args, ask the interceptor for a
verdict, honour a ``pending`` approval round-trip, deny by raising when the
verdict is ``deny``, otherwise run the original inside a spawn-context scope and
record the result. That shared body — previously duplicated verbatim in both
adapters (the cross-file duplication SonarCloud flagged on PR #269, AAASM-4746) —
lives here so each adapter keeps only its framework-specific glue.

The fail-closed-under-enforce contract from AAASM-4734 is preserved exactly: the
``enforce`` flag is threaded through ``_normalize_decision`` and a
``check_tool_start``-less interceptor falls back to
``_missing_interceptor_decision`` (both re-used from the CrewAI leaf helpers), so
an unrecognized verdict or a missing ``check_tool_start`` still denies under
enforce.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from agent_assembly.exceptions import PolicyViolationError

from agent_assembly.adapters.crewai.patch import (
    _get_pending_tool_approval_timeout_seconds as _resolve_pending_timeout_seconds,
)
from agent_assembly.adapters.crewai.patch import (
    _missing_interceptor_decision,
)
from agent_assembly.adapters.crewai.patch import (
    _normalize_decision as _normalize_governance_decision,
)
from agent_assembly.core.spawn import _SPAWN_CTX, SpawnContext, spawn_context_scope

_MAX_AUDIT_RESULT_CHARS = 2000


def _current_spawn_depth() -> int:
    current = _SPAWN_CTX.get()
    return (current.depth + 1) if current is not None else 1


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
    *,
    enforce: bool = False,
) -> tuple[Literal["allow", "deny", "pending"], str | None]:
    return _normalize_governance_decision(decision, enforce=enforce)


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
        return _missing_interceptor_decision(callback_handler)

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


def _build_denied_error(tool_name: str, reason: str | None) -> PolicyViolationError:
    from agent_assembly.exceptions import PolicyViolationError

    reason_text = reason or "No reason provided."
    return PolicyViolationError(f"Tool '{tool_name}' blocked by governance policy: {reason_text}")


def _build_pending_rejected_error(tool_name: str, reason: str | None) -> PolicyViolationError:
    from agent_assembly.exceptions import PolicyViolationError

    reason_text = reason or "No reason provided."
    return PolicyViolationError(f"Tool '{tool_name}' rejected during approval: {reason_text}")


async def run_governed_async_tool(
    callback_handler: Any,
    *,
    enforce: bool,
    tool_name: str,
    tool_args: dict[str, Any],
    agent_id: str | None,
    run_id: str | None,
    invoke_original: Callable[[], Any],
) -> Any:
    """Run one intercepted async tool call through the governance flow.

    Applies the pre-execution check (with a ``pending`` approval round-trip),
    raises on ``deny``, then runs ``invoke_original`` inside a spawn-context scope
    and records the result. ``invoke_original`` is a zero-argument callable that
    the adapter supplies to call the framework's original method with its own
    signature; it may return an awaitable, which is awaited here.

    Raises:
        PolicyViolationError: When the (final) verdict is ``deny`` — a
            pending-rejection message when the deny followed an approval
            round-trip, otherwise the blocked-by-policy message.
    """
    decision = await _invoke_async_tool_check(
        callback_handler,
        tool_name=tool_name,
        tool_args=tool_args,
        agent_id=agent_id,
        run_id=run_id,
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
            run_id=run_id,
        )
        status, reason = _normalize_decision(final_decision, enforce=enforce)

    # Fail closed: only an explicit "allow" may proceed. A terminal "pending"
    # (approval timed out or the resolver returned pending again) is a
    # non-decision, not a grant — blocking it here stops it from falling through
    # and running the tool, matching the LangChain handler.
    if status != "allow":
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
        result = invoke_original()
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
