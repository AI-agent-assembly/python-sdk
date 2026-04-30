"""MCP client patch module."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import importlib.util
import inspect
from typing import Any, Literal, Mapping

from agent_assembly.adapters.crewai.patch import (
    _get_pending_tool_approval_timeout_seconds as _resolve_pending_timeout_seconds,
)
from agent_assembly.adapters.crewai.patch import _normalize_decision as _normalize_governance_decision

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
        _ = self.callback_handler
        return _is_mcp_available()

    def revert(self) -> None:
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
) -> tuple[Literal["allow", "deny", "pending"], str | None]:
    return _normalize_governance_decision(decision)


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
) -> Exception:
    from agent_assembly.exceptions import MCPToolBlockedError

    reason_text = reason or "No reason provided."
    if is_pending_rejection:
        message = (
            f"MCP tool '{tool_name}' on server '{server_identifier}' "
            f"rejected during approval: {reason_text}"
        )
    else:
        message = (
            f"MCP tool '{tool_name}' on server '{server_identifier}' "
            f"blocked by governance policy: {reason_text}"
        )

    return MCPToolBlockedError(
        message,
        tool_name=tool_name,
        server=server_identifier,
    )
