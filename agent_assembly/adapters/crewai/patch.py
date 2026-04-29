"""CrewAI patch module."""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
import importlib
from threading import local
from typing import Any, Literal, Mapping

_TOOLS_PATCHED_FLAG = "_agent_assembly_crewai_tools_patched"
_TASK_PATCHED_FLAG = "_agent_assembly_crewai_task_patched"
_ORIGINAL_TOOL_RUN = "_agent_assembly_original_crewai_tool_run"
_ORIGINAL_TASK_EXECUTE_SYNC = "_agent_assembly_original_crewai_task_execute_sync"
_AGENT_CONTEXT = local()
_DEFAULT_PENDING_APPROVAL_TIMEOUT_SECONDS = 300


@dataclass(slots=True)
class CrewAIPatch:
    """Applies CrewAI runtime monkey-patching hooks."""

    callback_handler: Any

    def apply(self) -> bool:
        """Apply patch wiring and return whether CrewAI is available."""
        base_tool_cls = _load_crewai_basetool_class()
        if base_tool_cls is None:
            return False

        _apply_basetool_run_patch(base_tool_cls, self.callback_handler)
        task_cls = _load_crewai_task_class()
        if task_cls is not None:
            _apply_task_execute_sync_patch(task_cls, self.callback_handler)
        return True

    def revert(self) -> None:
        """Revert CrewAI runtime monkey patches when available."""
        base_tool_cls = _load_crewai_basetool_class()
        if base_tool_cls is not None:
            _revert_basetool_run_patch(base_tool_cls)

        task_cls = _load_crewai_task_class()
        if task_cls is not None:
            _revert_task_execute_sync_patch(task_cls)
        return None


def _load_crewai_basetool_class() -> type[Any] | None:
    try:
        module = importlib.import_module("crewai.tools")
    except ImportError:
        return None

    base_tool_cls = getattr(module, "BaseTool", None)
    if isinstance(base_tool_cls, type):
        return base_tool_cls
    return None


def _load_crewai_task_class() -> type[Any] | None:
    try:
        module = importlib.import_module("crewai")
    except ImportError:
        return None

    task_cls = getattr(module, "Task", None)
    if isinstance(task_cls, type):
        return task_cls
    return None


def _set_thread_local_agent_id(agent_id: str | None) -> None:
    _AGENT_CONTEXT.agent_id = agent_id


def _get_thread_local_agent_id() -> str | None:
    agent_id = getattr(_AGENT_CONTEXT, "agent_id", None)
    if isinstance(agent_id, str) and agent_id:
        return agent_id
    return None


def _extract_agent_id_from_inputs(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    direct_agent_id = kwargs.get("agent_id")
    if isinstance(direct_agent_id, str) and direct_agent_id:
        return direct_agent_id

    config = kwargs.get("config")
    if isinstance(config, dict):
        configurable = config.get("configurable")
        if isinstance(configurable, dict):
            configurable_agent_id = configurable.get("agent_id")
            if isinstance(configurable_agent_id, str) and configurable_agent_id:
                return configurable_agent_id

        metadata = config.get("metadata")
        if isinstance(metadata, dict):
            metadata_agent_id = metadata.get("agent_id")
            if isinstance(metadata_agent_id, str) and metadata_agent_id:
                return metadata_agent_id

    if args and isinstance(args[0], dict):
        state_agent_id = args[0].get("agent_id")
        if isinstance(state_agent_id, str) and state_agent_id:
            return state_agent_id

    return None


def _format_blocked_message(reason: str | None) -> str:
    reason_text = reason or "No reason provided."
    return (
        f"[BLOCKED by governance policy] {reason_text}. "
        "Please choose a different approach to accomplish this task."
    )


def _format_approval_rejected_message(reason: str | None) -> str:
    reason_text = reason or "No reason provided."
    return f"[APPROVAL REJECTED] Action was reviewed and denied: {reason_text}"


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


def _invoke_sync_tool_check(
    callback_handler: Any,
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    agent_id: str | None,
) -> object:
    method = getattr(callback_handler, "check_tool_start", None)
    if callable(method):
        return method(
            serialized={"name": tool_name},
            input_str=str(tool_args),
            tool_name=tool_name,
            args=tool_args,
            agent_id=agent_id,
        )

    return {"status": "allow"}


def _wait_for_sync_tool_approval(
    callback_handler: Any,
    *,
    tool_name: str,
    timeout_seconds: int,
    tool_args: dict[str, Any],
    agent_id: str | None,
) -> object:
    method = getattr(callback_handler, "wait_for_tool_approval", None)
    if callable(method):
        return method(
            tool_name=tool_name,
            timeout_seconds=timeout_seconds,
            args=tool_args,
            agent_id=agent_id,
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


def _record_sync_tool_result(
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


def _apply_basetool_run_patch(base_tool_cls: type[Any], callback_handler: Any) -> None:
    if getattr(base_tool_cls, _TOOLS_PATCHED_FLAG, False):
        return None

    original_run = base_tool_cls.run

    @wraps(original_run)
    def patched_run(self: Any, *args: Any, **kwargs: Any) -> Any:
        tool_name = getattr(self, "name", self.__class__.__name__)
        tool_args = dict(kwargs)
        agent_id = _get_thread_local_agent_id()
        decision = _invoke_sync_tool_check(
            callback_handler,
            tool_name=str(tool_name),
            tool_args=tool_args,
            agent_id=agent_id,
        )
        status, reason = _normalize_decision(decision)
        is_pending_flow = False
        if status == "pending":
            is_pending_flow = True
            timeout_seconds = _get_pending_tool_approval_timeout_seconds(callback_handler)
            final_decision = _wait_for_sync_tool_approval(
                callback_handler,
                tool_name=str(tool_name),
                timeout_seconds=timeout_seconds,
                tool_args=tool_args,
                agent_id=agent_id,
            )
            status, reason = _normalize_decision(final_decision)

        if status == "deny":
            if is_pending_flow:
                return _format_approval_rejected_message(reason)
            return _format_blocked_message(reason)

        result = original_run(self, *args, **kwargs)
        _record_sync_tool_result(callback_handler, tool_name=str(tool_name), result=result)
        return result

    setattr(base_tool_cls, _ORIGINAL_TOOL_RUN, original_run)
    setattr(base_tool_cls, "run", patched_run)
    setattr(base_tool_cls, _TOOLS_PATCHED_FLAG, True)


def _revert_basetool_run_patch(base_tool_cls: type[Any]) -> None:
    if not getattr(base_tool_cls, _TOOLS_PATCHED_FLAG, False):
        return None

    original_run = getattr(base_tool_cls, _ORIGINAL_TOOL_RUN, None)
    if callable(original_run):
        setattr(base_tool_cls, "run", original_run)

    if hasattr(base_tool_cls, _ORIGINAL_TOOL_RUN):
        delattr(base_tool_cls, _ORIGINAL_TOOL_RUN)
    if hasattr(base_tool_cls, _TOOLS_PATCHED_FLAG):
        delattr(base_tool_cls, _TOOLS_PATCHED_FLAG)
    return None


def _record_task_start(callback_handler: Any, task: Any) -> None:
    method = getattr(callback_handler, "record", None)
    if callable(method):
        method(
            action="task_start",
            task_description=str(getattr(task, "description", ""))[:200],
            expected_output=getattr(task, "expected_output", None),
        )
        return None

    fallback = getattr(callback_handler, "on_task_start", None)
    if callable(fallback):
        fallback(task=task)
    return None


def _record_task_complete(callback_handler: Any, result: object) -> None:
    method = getattr(callback_handler, "record", None)
    if callable(method):
        method(action="task_complete", output_preview=str(result)[:500])
        return None

    fallback = getattr(callback_handler, "on_task_complete", None)
    if callable(fallback):
        fallback(result=result)
    return None


def _apply_task_execute_sync_patch(task_cls: type[Any], callback_handler: Any) -> None:
    if getattr(task_cls, _TASK_PATCHED_FLAG, False):
        return None

    original_execute_sync = task_cls.execute_sync

    @wraps(original_execute_sync)
    def patched_execute_sync(self: Any, *args: Any, **kwargs: Any) -> Any:
        previous_agent_id = _get_thread_local_agent_id()
        _set_thread_local_agent_id(_extract_agent_id_from_inputs(args, kwargs))
        _record_task_start(callback_handler, self)
        try:
            result = original_execute_sync(self, *args, **kwargs)
        finally:
            _set_thread_local_agent_id(previous_agent_id)

        _record_task_complete(callback_handler, result)
        return result

    setattr(task_cls, _ORIGINAL_TASK_EXECUTE_SYNC, original_execute_sync)
    setattr(task_cls, "execute_sync", patched_execute_sync)
    setattr(task_cls, _TASK_PATCHED_FLAG, True)


def _revert_task_execute_sync_patch(task_cls: type[Any]) -> None:
    if not getattr(task_cls, _TASK_PATCHED_FLAG, False):
        return None

    original_execute_sync = getattr(task_cls, _ORIGINAL_TASK_EXECUTE_SYNC, None)
    if callable(original_execute_sync):
        setattr(task_cls, "execute_sync", original_execute_sync)

    if hasattr(task_cls, _ORIGINAL_TASK_EXECUTE_SYNC):
        delattr(task_cls, _ORIGINAL_TASK_EXECUTE_SYNC)
    if hasattr(task_cls, _TASK_PATCHED_FLAG):
        delattr(task_cls, _TASK_PATCHED_FLAG)
    return None
