"""Haystack runtime monkey-patch.

Haystack (deepset; ``pip install haystack-ai``, imported as ``haystack``) executes
every tool through ``haystack.tools.Tool.invoke(**kwargs)``.  The agentic
``haystack.components.agents.Agent`` dispatches its tool calls via
``haystack.components.tools.ToolInvoker``, which itself ends up calling
``tool_to_invoke.invoke(**final_args)`` (see ``ToolInvoker._make_context_bound_invoke``
in Haystack 2.x).  ``Tool.invoke`` is therefore the *single* execution chokepoint that
governs both the bare ``Tool.invoke()`` path and the full Agent tool-call loop —
patching it intercepts every tool execution, which is why governance is wired here and
not at the higher-level ``Agent`` / ``ToolInvoker`` layer.

The interceptor contract mirrors the other tool-call adapters (CrewAI, Pydantic AI):
a ``check_tool_start`` pre-execution gate that returns ``allow`` / ``deny`` /
``pending``, an optional ``wait_for_tool_approval`` for the pending flow, and a
post-execution ``record_result`` / ``on_tool_end`` audit hook — which the SDK's own
interceptor resolves over a connected runtime, forwarding the outcome to the
runtime's audit pipeline, and does not resolve without one (AAASM-5750).
Under the fail-closed
``enforce`` posture an unknown or malformed verdict denies (AAASM-3107).
"""

from __future__ import annotations

import importlib as importlib
from collections.abc import Mapping
from dataclasses import dataclass
from functools import wraps
from typing import Any, Literal, cast

from agent_assembly.adapters._shared.positional_args import merge_positional_tool_args

_TOOL_PATCHED_FLAG = "_agent_assembly_haystack_tool_patched"
_ORIGINAL_TOOL_INVOKE = "_agent_assembly_original_haystack_tool_invoke"
_DEFAULT_PENDING_APPROVAL_TIMEOUT_SECONDS = 300


@dataclass(slots=True)
class HaystackPatch:
    """Applies Haystack runtime monkey-patching hooks on ``Tool.invoke``."""

    callback_handler: Any

    def apply(self) -> bool:
        """Patch ``Tool.invoke`` and return whether Haystack is available."""
        tool_cls = _load_haystack_tool_class()
        if tool_cls is None:
            return False
        _apply_tool_invoke_patch(tool_cls, self.callback_handler)
        return True

    def revert(self) -> None:
        """Revert the ``Tool.invoke`` monkey patch when present."""
        tool_cls = _load_haystack_tool_class()
        if tool_cls is not None:
            _revert_tool_invoke_patch(tool_cls)
        return None


def _load_haystack_tool_class() -> type[Any] | None:
    try:
        module = importlib.import_module("haystack.tools")
    except ImportError:
        return None

    tool_cls = getattr(module, "Tool", None)
    if isinstance(tool_cls, type):
        return tool_cls
    return None


def _format_blocked_message(reason: str | None) -> str:
    reason_text = reason or "No reason provided."
    return f"[BLOCKED by governance policy] {reason_text}. Please choose a different approach to accomplish this task."


def _format_approval_rejected_message(reason: str | None) -> str:
    reason_text = reason or "No reason provided."
    return f"[APPROVAL REJECTED] Action was reviewed and denied: {reason_text}"


_UNKNOWN_DECISION_REASON = "Unrecognized governance decision; denied under enforce."


def _interceptor_enforces(callback_handler: Any) -> bool:
    """Return whether the wired interceptor is in fail-closed ``enforce`` posture.

    The governance interceptor carries ``_enforce`` set from
    ``enforcement_mode == "enforce"`` (AAASM-3106).  A bare ``GatewayClient`` has no
    such attribute and defaults to fail-open.  Compared strictly against ``True`` so a
    stub interceptor whose ``__getattr__`` synthesizes truthy values for missing
    attributes is not mistaken for the enforce posture; the real flag is always a
    ``bool``.
    """
    target = getattr(callback_handler, "_interceptor", callback_handler)
    return getattr(target, "_enforce", False) is True


def _unknown_decision(enforce: bool) -> tuple[Literal["allow", "deny", "pending"], str | None]:
    """Map an unrecognized / malformed verdict, failing closed under ``enforce`` (AAASM-3107)."""
    if enforce:
        return "deny", _UNKNOWN_DECISION_REASON
    return "allow", None


_MISSING_INTERCEPTOR_REASON = "Governance interceptor exposes no check_tool_start; denied under enforce."


def _missing_interceptor_decision(callback_handler: Any) -> dict[str, str]:
    """Fallback verdict when the wired interceptor has no ``check_tool_start``.

    A co-installed adapter can be handed a callback handler lacking
    ``check_tool_start`` (e.g. LangChain's ``AssemblyCallbackHandler`` before the
    AAASM-4014 delegation fix). Defaulting to ``allow`` silently skipped
    pre-execution governance; this fails closed under ``enforce`` (deny) and
    proceeds under observe / disabled (fail open).
    """
    if _interceptor_enforces(callback_handler):
        return {"status": "deny", "reason": _MISSING_INTERCEPTOR_REASON}
    return {"status": "allow"}


_KNOWN_STATUSES: frozenset[str] = frozenset({"allow", "deny", "pending"})


def _coerce_known_status(value: str) -> Literal["allow", "deny", "pending"] | None:
    if value in _KNOWN_STATUSES:
        return cast("Literal['allow', 'deny', 'pending']", value)
    return None


def _normalize_decision(
    decision: object,
    *,
    enforce: bool = False,
) -> tuple[Literal["allow", "deny", "pending"], str | None]:
    if isinstance(decision, str):
        status = _coerce_known_status(decision.strip().lower())
        if status is not None:
            return status, None
        return _unknown_decision(enforce)

    if isinstance(decision, Mapping):
        reason_value = decision.get("reason")
        reason = str(reason_value) if reason_value is not None else None
        status = _coerce_known_status(str(decision.get("status", "")).strip().lower())
        if status is not None:
            return status, reason
        unknown_status, unknown_reason = _unknown_decision(enforce)
        return unknown_status, reason if reason is not None else unknown_reason

    return _unknown_decision(enforce)


def _invoke_tool_check(
    callback_handler: Any,
    *,
    tool_name: str,
    tool_args: dict[str, Any],
) -> object:
    method = getattr(callback_handler, "check_tool_start", None)
    if callable(method):
        return method(
            serialized={"name": tool_name},
            input_str=str(tool_args),
            tool_name=tool_name,
            args=tool_args,
            agent_id=None,
        )
    return _missing_interceptor_decision(callback_handler)


def _wait_for_tool_approval(
    callback_handler: Any,
    *,
    tool_name: str,
    timeout_seconds: int,
    tool_args: dict[str, Any],
) -> object:
    method = getattr(callback_handler, "wait_for_tool_approval", None)
    if callable(method):
        return method(
            tool_name=tool_name,
            timeout_seconds=timeout_seconds,
            args=tool_args,
            agent_id=None,
        )
    return {"status": "deny", "reason": "Approval handler is unavailable."}


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


def _record_tool_result(
    callback_handler: Any,
    *,
    tool_name: str,
    result: object,
) -> None:
    record_method = getattr(callback_handler, "record_result", None)
    if callable(record_method):
        record_method(tool_name=tool_name, result=result)
        return None

    tool_end_method = getattr(callback_handler, "on_tool_end", None)
    if callable(tool_end_method):
        tool_end_method(output=result, tool_name=tool_name)
    return None


def _apply_tool_invoke_patch(tool_cls: type[Any], callback_handler: Any) -> None:
    if getattr(tool_cls, _TOOL_PATCHED_FLAG, False):
        return None

    original_invoke = tool_cls.invoke
    enforce = _interceptor_enforces(callback_handler)

    @wraps(original_invoke)
    def patched_invoke(self: Any, *args: Any, **kwargs: Any) -> Any:
        tool_name = str(getattr(self, "name", self.__class__.__name__))
        # Haystack's ToolInvoker calls ``invoke(**final_args)`` (keyword-only), but
        # a direct ``Tool.invoke(x)`` positional call must be governed and forwarded
        # too. Fold any positional args into tool_args so content policy inspects
        # their values rather than seeing an empty mapping.
        tool_args = merge_positional_tool_args(dict(kwargs), args)
        decision = _invoke_tool_check(
            callback_handler,
            tool_name=tool_name,
            tool_args=tool_args,
        )
        status, reason = _normalize_decision(decision, enforce=enforce)
        is_pending_flow = False
        if status == "pending":
            is_pending_flow = True
            timeout_seconds = _get_pending_tool_approval_timeout_seconds(callback_handler)
            final_decision = _wait_for_tool_approval(
                callback_handler,
                tool_name=tool_name,
                timeout_seconds=timeout_seconds,
                tool_args=tool_args,
            )
            status, reason = _normalize_decision(final_decision, enforce=enforce)

        # Fail closed: only an explicit "allow" may proceed. A terminal "pending"
        # (approval timed out or the resolver returned pending again) is a
        # non-decision, not a grant — blocking it here stops it from falling
        # through and running the tool, matching the LangChain handler.
        if status != "allow":
            if is_pending_flow:
                return _format_approval_rejected_message(reason)
            return _format_blocked_message(reason)

        result = original_invoke(self, *args, **kwargs)
        _record_tool_result(callback_handler, tool_name=tool_name, result=result)
        return result

    setattr(tool_cls, _ORIGINAL_TOOL_INVOKE, original_invoke)
    tool_cls.invoke = patched_invoke
    setattr(tool_cls, _TOOL_PATCHED_FLAG, True)


def _revert_tool_invoke_patch(tool_cls: type[Any]) -> None:
    if not getattr(tool_cls, _TOOL_PATCHED_FLAG, False):
        return None

    original_invoke = getattr(tool_cls, _ORIGINAL_TOOL_INVOKE, None)
    if callable(original_invoke):
        tool_cls.invoke = original_invoke

    if hasattr(tool_cls, _ORIGINAL_TOOL_INVOKE):
        delattr(tool_cls, _ORIGINAL_TOOL_INVOKE)
    if hasattr(tool_cls, _TOOL_PATCHED_FLAG):
        delattr(tool_cls, _TOOL_PATCHED_FLAG)
    return None
