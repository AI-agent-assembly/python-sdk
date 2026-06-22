"""Agno (formerly Phidata) patch module.

Agno (pip ``agno``) runs **every** function-tool body through a single
chokepoint: ``agno.tools.function.FunctionCall.execute`` (sync) and
``FunctionCall.aexecute`` (async). An ``Agent`` builds a ``FunctionCall`` from the
model's tool-call request and invokes ``execute()``/``aexecute()``, which calls
the user's tool entrypoint and wraps the return in a ``FunctionExecutionResult``.

Patching that one method is therefore the SDK-layer interception point for Agno:
it sits *before* the tool body runs, so a governance ``deny`` short-circuits the
body entirely (the tool never executes) and an ``allow`` runs it and records the
result. This is the same pre-execution allow/deny contract the CrewAI / Pydantic
AI adapters implement on ``BaseTool.run`` / ``Tool._run``, reusing the shared
decision-normalization and approval helpers from
``agent_assembly.adapters.crewai.patch`` so the fail-closed-under-enforce posture
(AAASM-3107) is identical across adapters.
"""

from __future__ import annotations

import importlib as importlib
import inspect
from dataclasses import dataclass
from functools import wraps
from typing import Any

from agent_assembly.adapters.crewai.patch import (
    _format_approval_rejected_message as _format_approval_rejected,
)
from agent_assembly.adapters.crewai.patch import (
    _format_blocked_message as _format_blocked,
)
from agent_assembly.adapters.crewai.patch import (
    _get_pending_tool_approval_timeout_seconds as _resolve_pending_timeout_seconds,
)
from agent_assembly.adapters.crewai.patch import (
    _interceptor_enforces,
)
from agent_assembly.adapters.crewai.patch import (
    _invoke_sync_tool_check as _invoke_tool_check,
)
from agent_assembly.adapters.crewai.patch import (
    _normalize_decision as _normalize_governance_decision,
)
from agent_assembly.adapters.crewai.patch import (
    _record_sync_tool_result as _record_tool_result,
)
from agent_assembly.adapters.crewai.patch import (
    _wait_for_sync_tool_approval as _wait_for_tool_approval,
)

_TOOLS_PATCHED_FLAG = "_agent_assembly_agno_functioncall_patched"
_ORIGINAL_EXECUTE = "_agent_assembly_original_agno_functioncall_execute"
_ORIGINAL_AEXECUTE = "_agent_assembly_original_agno_functioncall_aexecute"


@dataclass(slots=True)
class AgnoPatch:
    """Applies Agno runtime monkey-patching hooks on ``FunctionCall.execute``."""

    callback_handler: Any

    def apply(self) -> bool:
        """Patch ``FunctionCall.execute``/``aexecute`` and report availability.

        Returns:
            ``True`` when the Agno ``FunctionCall`` class was found and the
            governance hook installed; ``False`` (a no-op) when ``agno`` is not
            importable or the expected hook point is absent — never raises
            ``AttributeError`` on a missing framework.
        """
        function_call_cls = _load_agno_functioncall_class()
        if function_call_cls is None:
            return False
        return _apply_execute_patch(function_call_cls, self.callback_handler)

    def revert(self) -> None:
        """Revert the Agno ``FunctionCall`` patches when present."""
        function_call_cls = _load_agno_functioncall_class()
        if function_call_cls is not None:
            _revert_execute_patch(function_call_cls)
        return None


def _load_agno_functioncall_class() -> type[Any] | None:
    try:
        module = importlib.import_module("agno.tools.function")
    except ImportError:
        return None

    function_call_cls = getattr(module, "FunctionCall", None)
    if isinstance(function_call_cls, type):
        return function_call_cls
    return None


def _load_agno_failure_result_factory() -> Any | None:
    """Return a callable building a failure ``FunctionExecutionResult``, or None.

    A governance ``deny`` must short-circuit a tool with a result object that
    Agno's calling code understands. ``FunctionExecutionResult(status="failure",
    error=...)`` is exactly what ``execute()`` returns on a failed tool, so the
    denied message flows back to the model as a tool error rather than a tool
    result — the body never runs.
    """
    try:
        module = importlib.import_module("agno.tools.function")
    except ImportError:
        return None
    return getattr(module, "FunctionExecutionResult", None)


def _build_denied_result(message: str) -> Any:
    """Wrap a governance block message in an Agno failure result.

    Falls back to returning the raw string when the result type cannot be
    constructed (e.g. a future Agno that renames it), so a deny still blocks the
    body even if the wrapper shape changed.
    """
    factory = _load_agno_failure_result_factory()
    if factory is None:
        return message
    try:
        return factory(status="failure", error=message)
    except Exception:
        return message


def _resolve_tool_name(function_call: Any) -> str:
    function = getattr(function_call, "function", None)
    name = getattr(function, "name", None)
    if isinstance(name, str) and name:
        return name
    return str(function_call.__class__.__name__)


def _resolve_tool_args(function_call: Any) -> dict[str, Any]:
    arguments = getattr(function_call, "arguments", None)
    if isinstance(arguments, dict):
        return dict(arguments)
    return {}


def _evaluate_decision(
    callback_handler: Any,
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    enforce: bool,
) -> tuple[str, str | None, bool]:
    """Run the pre-execution governance check and resolve a final verdict.

    Returns ``(status, reason, is_pending_flow)`` where ``status`` is one of
    ``allow`` / ``deny`` (``pending`` is resolved here by waiting for approval).
    """
    decision = _invoke_tool_check(
        callback_handler,
        tool_name=tool_name,
        tool_args=tool_args,
        agent_id=None,
    )
    status, reason = _normalize_governance_decision(decision, enforce=enforce)
    is_pending_flow = False
    if status == "pending":
        is_pending_flow = True
        timeout_seconds = _resolve_pending_timeout_seconds(callback_handler)
        final_decision = _wait_for_tool_approval(
            callback_handler,
            tool_name=tool_name,
            timeout_seconds=timeout_seconds,
            tool_args=tool_args,
            agent_id=None,
        )
        status, reason = _normalize_governance_decision(final_decision, enforce=enforce)
    return status, reason, is_pending_flow


def _apply_execute_patch(function_call_cls: type[Any], callback_handler: Any) -> bool:
    if getattr(function_call_cls, _TOOLS_PATCHED_FLAG, False):
        return True

    original_execute = function_call_cls.execute
    original_aexecute = getattr(function_call_cls, "aexecute", None)
    enforce = _interceptor_enforces(callback_handler)

    @wraps(original_execute)
    def patched_execute(self: Any, *args: Any, **kwargs: Any) -> Any:
        tool_name = _resolve_tool_name(self)
        tool_args = _resolve_tool_args(self)
        status, reason, is_pending_flow = _evaluate_decision(
            callback_handler,
            tool_name=tool_name,
            tool_args=tool_args,
            enforce=enforce,
        )
        if status == "deny":
            message = _format_approval_rejected(reason) if is_pending_flow else _format_blocked(reason)
            return _build_denied_result(message)

        result = original_execute(self, *args, **kwargs)
        _record_tool_result(callback_handler, tool_name=tool_name, result=result)
        return result

    setattr(function_call_cls, _ORIGINAL_EXECUTE, original_execute)
    function_call_cls.execute = patched_execute

    if inspect.iscoroutinefunction(original_aexecute):

        @wraps(original_aexecute)
        async def patched_aexecute(self: Any, *args: Any, **kwargs: Any) -> Any:
            tool_name = _resolve_tool_name(self)
            tool_args = _resolve_tool_args(self)
            status, reason, is_pending_flow = _evaluate_decision(
                callback_handler,
                tool_name=tool_name,
                tool_args=tool_args,
                enforce=enforce,
            )
            if status == "deny":
                message = _format_approval_rejected(reason) if is_pending_flow else _format_blocked(reason)
                return _build_denied_result(message)

            result = await original_aexecute(self, *args, **kwargs)
            _record_tool_result(callback_handler, tool_name=tool_name, result=result)
            return result

        setattr(function_call_cls, _ORIGINAL_AEXECUTE, original_aexecute)
        function_call_cls.aexecute = patched_aexecute

    setattr(function_call_cls, _TOOLS_PATCHED_FLAG, True)
    return True


def _revert_execute_patch(function_call_cls: type[Any]) -> None:
    if not getattr(function_call_cls, _TOOLS_PATCHED_FLAG, False):
        return None

    original_execute = getattr(function_call_cls, _ORIGINAL_EXECUTE, None)
    if callable(original_execute):
        function_call_cls.execute = original_execute

    original_aexecute = getattr(function_call_cls, _ORIGINAL_AEXECUTE, None)
    if callable(original_aexecute):
        function_call_cls.aexecute = original_aexecute

    for attr in (_ORIGINAL_EXECUTE, _ORIGINAL_AEXECUTE, _TOOLS_PATCHED_FLAG):
        if hasattr(function_call_cls, attr):
            delattr(function_call_cls, attr)
    return None
