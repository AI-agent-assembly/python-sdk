"""Hand a denied tool call's outcome to the adapter's audit hook.

Most adapters return or raise at their ``if status != "allow":`` branch, so
before AAASM-5787 a denied call built no record at all — the interceptor's sink
had nothing to forward, however it was configured. This module is what those
branches call.

It is a leaf: it imports no adapter, so any adapter can import it without the
cycle that ``_shared.tool_governance`` would create (that module imports
``crewai.patch``). ``_shared.positional_args`` is the same shape.

What a call here does and does not establish
--------------------------------------------
Handing the record to the hook is a *handoff*. Over a connected runtime the
SDK's own interceptor resolves ``record_result`` and writes to the native event
channel (AAASM-5750); without one, neither hook resolves and this emits nothing.
Neither case is ADR 0033 §6 *Observed* — that term asks for a durable event
attributed to the action, and AAASM-5783 is open on ``report_event`` payloads
reaching neither the live stream nor the durable entry. What the deny branch
gets from this module is that the record now exists to be forwarded, which is
upstream of the question AAASM-5783 asks.

Exceptions are suppressed here rather than at each call site. The hook is
duck-typed from caller-supplied code, and these calls are being inserted where
none used to exist: a raising handler would otherwise replace a decided deny
with its own exception, and a caller matching on ``PolicyViolationError`` would
stop recognising the deny. A decided deny is final regardless of audit outcome —
settled for the ``openai_agents`` path under AAASM-4782, followed rather than
re-answered here.
"""

from __future__ import annotations

import contextlib
import inspect
from typing import Any

MAX_AUDIT_RESULT_CHARS = 2000

_KEYWORD_PARAMETER_KINDS = (
    inspect.Parameter.POSITIONAL_OR_KEYWORD,
    inspect.Parameter.KEYWORD_ONLY,
)


def truncate_result_for_audit(result: object) -> str:
    return str(result)[:MAX_AUDIT_RESULT_CHARS]


def accepts_keyword(method: Any, name: str) -> bool:
    """Whether ``method`` can be called with the ``name`` keyword.

    The audit hook is duck-typed — adapters and user code supply their own
    ``record_result`` / ``on_tool_end`` — and the implementations that predate
    the denial flag were written without it, so passing it unconditionally
    would raise ``TypeError`` on them. The flag is therefore offered only to
    handlers that can receive it (an explicit parameter or a ``**kwargs``
    catch-all); the rest still get the record, just without the flag.
    """
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        # C-implemented callables expose no introspectable signature. Fall back
        # to the narrow call so the record is still emitted.
        return False
    for parameter in signature.parameters.values():
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            return True
        if parameter.name == name and parameter.kind in _KEYWORD_PARAMETER_KINDS:
            return True
    return False


def _offer(
    callback_handler: Any,
    *,
    tool_name: str,
    result: object,
    agent_id: str | None,
    run_id: str | None,
) -> object | None:
    """Call the first hook the handler exposes; return whatever it returned.

    The return value matters to the async entry point, which has to await a
    coroutine hook. The sync entry point closes one instead — see there for why.
    """
    denial_flag = {"denied": True}
    payload = truncate_result_for_audit(result)

    record_method = getattr(callback_handler, "record_result", None)
    if callable(record_method):
        returned: object = record_method(
            tool_name=tool_name,
            result=payload,
            agent_id=agent_id,
            run_id=run_id,
            **(denial_flag if accepts_keyword(record_method, "denied") else {}),
        )
        return returned

    tool_end_method = getattr(callback_handler, "on_tool_end", None)
    if callable(tool_end_method):
        ended: object = tool_end_method(
            output=payload,
            tool_name=tool_name,
            agent_id=agent_id,
            run_id=run_id,
            **(denial_flag if accepts_keyword(tool_end_method, "denied") else {}),
        )
        return ended

    return None


def record_denied_tool_result(
    callback_handler: Any,
    *,
    tool_name: str,
    result: object,
    agent_id: str | None = None,
    run_id: str | None = None,
) -> None:
    """Offer a denied call's record from a synchronous deny branch."""
    with contextlib.suppress(Exception):
        returned = _offer(
            callback_handler,
            tool_name=tool_name,
            result=result,
            agent_id=agent_id,
            run_id=run_id,
        )
        if inspect.iscoroutine(returned):
            # A sync deny branch has no loop to await on. Close it rather than
            # abandon it: an un-awaited coroutine emits a RuntimeWarning at
            # collection time, from this module, in a run whose real problem is
            # that the handler and the adapter disagree about sync vs async.
            returned.close()


async def arecord_denied_tool_result(
    callback_handler: Any,
    *,
    tool_name: str,
    result: object,
    agent_id: str | None = None,
    run_id: str | None = None,
) -> None:
    """Offer a denied call's record from an asynchronous deny branch."""
    with contextlib.suppress(Exception):
        returned = _offer(
            callback_handler,
            tool_name=tool_name,
            result=result,
            agent_id=agent_id,
            run_id=run_id,
        )
        if inspect.isawaitable(returned):
            await returned
