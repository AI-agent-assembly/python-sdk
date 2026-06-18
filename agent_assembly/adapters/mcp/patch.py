"""MCP client patch module."""

from __future__ import annotations

import importlib as importlib
import importlib.util
import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Mapping

if TYPE_CHECKING:
    from agent_assembly.exceptions import MCPToolBlockedError

from agent_assembly.adapters.crewai.patch import (
    _get_pending_tool_approval_timeout_seconds as _resolve_pending_timeout_seconds,
)
from agent_assembly.adapters.crewai.patch import (
    _interceptor_enforces as _resolve_interceptor_enforces,
)
from agent_assembly.adapters.crewai.patch import (
    _normalize_decision as _normalize_governance_decision,
)

_ORIGINAL_CALL_TOOL = "_agent_assembly_original_mcp_call_tool"
_PATCHED_FLAG = "_agent_assembly_mcp_clientsession_patched"
_PROCESS_AGENT_ID: str | None = None
_MAX_AUDIT_RESULT_CHARS = 2000


@dataclass(slots=True)
class MCPClientPatch:
    """Patch placeholder for MCP client interception."""

    callback_handler: Any
    process_agent_id: str | None = None

    def apply(self) -> bool:
        set_process_agent_id(self.process_agent_id)
        client_session_cls = _load_mcp_client_session_class()
        if client_session_cls is None:
            return False
        _apply_client_session_patch(client_session_cls, self.callback_handler)
        return True

    def revert(self) -> None:
        client_session_cls = _load_mcp_client_session_class()
        if client_session_cls is not None:
            _revert_client_session_patch(client_session_cls)
        set_process_agent_id(None)
        return None


def _is_mcp_available() -> bool:
    return importlib.util.find_spec("mcp") is not None


def set_process_agent_id(agent_id: str | None) -> None:
    global _PROCESS_AGENT_ID
    _PROCESS_AGENT_ID = agent_id


def _get_process_agent_id() -> str | None:
    if isinstance(_PROCESS_AGENT_ID, str) and _PROCESS_AGENT_ID:
        return _PROCESS_AGENT_ID
    return None


def _load_mcp_client_session_class() -> type[Any] | None:
    try:
        module = importlib.import_module("mcp")
    except ImportError:
        return None

    client_session_cls = getattr(module, "ClientSession", None)
    if isinstance(client_session_cls, type):
        return client_session_cls
    return None


def _get_server_identifier(session: Any) -> str:
    for attr in ("_server_url", "_server_name", "_ws_url"):
        value = getattr(session, attr, None)
        if isinstance(value, str) and value.strip():
            return value

    transport = getattr(session, "_transport", None)
    if transport is not None:
        for attr in ("url", "server_url", "server_name", "ws_url", "name"):
            value = getattr(transport, attr, None)
            if isinstance(value, str) and value.strip():
                return value

    return "mcp-unknown"


def _resolve_governance_target(callback_handler: Any) -> Any:
    target = getattr(callback_handler, "_interceptor", None)
    if target is not None:
        return target
    return callback_handler


def _extract_tool_call_inputs(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    raw_tool_name = kwargs.get("name")
    if not isinstance(raw_tool_name, str):
        raw_tool_name = str(args[0]) if args else "mcp-unknown-tool"

    raw_arguments = kwargs.get("arguments")
    if raw_arguments is None and len(args) >= 2:
        raw_arguments = args[1]

    if isinstance(raw_arguments, Mapping):
        return raw_tool_name, dict(raw_arguments)
    return raw_tool_name, {}


def _normalize_decision(
    decision: object,
    *,
    enforce: bool = False,
) -> tuple[Literal["allow", "deny", "pending"], str | None]:
    return _normalize_governance_decision(decision, enforce=enforce)


def _get_pending_tool_approval_timeout_seconds(callback_handler: Any) -> int:
    return _resolve_pending_timeout_seconds(callback_handler)


async def _invoke_async_tool_check(
    callback_handler: Any,
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    agent_id: str | None,
    server_identifier: str,
) -> object:
    target = _resolve_governance_target(callback_handler)
    method = getattr(target, "check_tool_start", None)
    if not callable(method):
        return {"status": "allow"}

    result = method(
        serialized={"name": tool_name},
        input_str=str(tool_args),
        tool_name=tool_name,
        args=tool_args,
        agent_id=agent_id,
        server=server_identifier,
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
    server_identifier: str,
) -> object:
    target = _resolve_governance_target(callback_handler)
    method = getattr(target, "wait_for_tool_approval", None)
    if not callable(method):
        return {"status": "deny", "reason": "Approval handler is unavailable."}

    result = method(
        serialized={"name": tool_name},
        input_str=str(tool_args),
        tool_name=tool_name,
        timeout_seconds=timeout_seconds,
        args=tool_args,
        agent_id=agent_id,
        server=server_identifier,
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
    server_identifier: str,
) -> None:
    target = _resolve_governance_target(callback_handler)

    record_method = getattr(target, "record_result", None)
    if callable(record_method):
        recorded = record_method(
            tool_name=tool_name,
            result=_truncate_result_for_audit(result),
            agent_id=agent_id,
            server=server_identifier,
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
            server=server_identifier,
        )
        if inspect.isawaitable(recorded):
            await recorded


def _build_blocked_error(
    *,
    tool_name: str,
    server_identifier: str,
    reason: str | None,
    is_pending_rejection: bool,
) -> MCPToolBlockedError:
    from agent_assembly.exceptions import MCPToolBlockedError

    reason_text = reason or "No reason provided."
    if is_pending_rejection:
        message = f"MCP tool '{tool_name}' on server '{server_identifier}' rejected during approval: {reason_text}"
    else:
        message = f"MCP tool '{tool_name}' on server '{server_identifier}' blocked by governance policy: {reason_text}"

    return MCPToolBlockedError(
        message,
        tool_name=tool_name,
        server=server_identifier,
    )


def _apply_client_session_patch(client_session_cls: type[Any], callback_handler: Any) -> None:
    if getattr(client_session_cls, _PATCHED_FLAG, False):
        return None

    original_call_tool = getattr(client_session_cls, "call_tool", None)
    if not callable(original_call_tool):
        return None

    enforce = _resolve_interceptor_enforces(callback_handler)

    async def patched_call_tool(self: Any, *args: Any, **kwargs: Any) -> Any:
        tool_name, tool_args = _extract_tool_call_inputs(args, kwargs)
        agent_id = _get_process_agent_id()
        server_identifier = _get_server_identifier(self)

        decision = await _invoke_async_tool_check(
            callback_handler,
            tool_name=tool_name,
            tool_args=tool_args,
            agent_id=agent_id,
            server_identifier=server_identifier,
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
                server_identifier=server_identifier,
            )
            status, reason = _normalize_decision(final_decision, enforce=enforce)

        if status == "deny":
            raise _build_blocked_error(
                tool_name=tool_name,
                server_identifier=server_identifier,
                reason=reason,
                is_pending_rejection=is_pending_flow,
            )

        result = original_call_tool(self, *args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        await _record_async_tool_result(
            callback_handler,
            tool_name=tool_name,
            result=result,
            agent_id=agent_id,
            server_identifier=server_identifier,
        )
        return result

    setattr(client_session_cls, _ORIGINAL_CALL_TOOL, original_call_tool)
    setattr(client_session_cls, "call_tool", patched_call_tool)
    setattr(client_session_cls, _PATCHED_FLAG, True)


def _revert_client_session_patch(client_session_cls: type[Any]) -> None:
    if not getattr(client_session_cls, _PATCHED_FLAG, False):
        return None

    original_call_tool = getattr(client_session_cls, _ORIGINAL_CALL_TOOL, None)
    if callable(original_call_tool):
        setattr(client_session_cls, "call_tool", original_call_tool)

    if hasattr(client_session_cls, _ORIGINAL_CALL_TOOL):
        delattr(client_session_cls, _ORIGINAL_CALL_TOOL)
    if hasattr(client_session_cls, _PATCHED_FLAG):
        delattr(client_session_cls, _PATCHED_FLAG)
