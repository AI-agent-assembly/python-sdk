"""CrewAI patch module."""

from __future__ import annotations

import importlib as importlib
from collections.abc import Mapping
from dataclasses import dataclass
from functools import wraps
from threading import local
from typing import Any, Literal, cast

from agent_assembly.core.spawn import _SPAWN_CTX, SpawnContext, spawn_context_scope

_TOOLS_PATCHED_FLAG = "_agent_assembly_crewai_tools_patched"
_TASK_PATCHED_FLAG = "_agent_assembly_crewai_task_patched"
_ORIGINAL_TOOL_RUN = "_agent_assembly_original_crewai_tool_run"
_ORIGINAL_TASK_EXECUTE_SYNC = "_agent_assembly_original_crewai_task_execute_sync"
_ORIGINAL_CREW_KICKOFF = "_agent_assembly_original_crewai_crew_kickoff"
_CREW_KICKOFF_PATCHED_FLAG = "_agent_assembly_crewai_crew_kickoff_patched"
_AGENT_CONTEXT = local()
_DEFAULT_PENDING_APPROVAL_TIMEOUT_SECONDS = 300
_MAX_DELEGATION_REASON_CHARS = 256


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
        crew_cls = _load_crewai_crew_class()
        if crew_cls is not None:
            _apply_crew_kickoff_patch(crew_cls)
        return True

    def revert(self) -> None:
        """Revert CrewAI runtime monkey patches when available."""
        crew_cls = _load_crewai_crew_class()
        if crew_cls is not None:
            _revert_crew_kickoff_patch(crew_cls)
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


def _load_crewai_crew_class() -> type[Any] | None:
    try:
        module = importlib.import_module("crewai")
    except ImportError:
        return None

    crew_cls = getattr(module, "Crew", None)
    if isinstance(crew_cls, type):
        return crew_cls
    return None


def _extract_crew_team_id(crew: Any) -> str | None:
    if crew is None:
        return None
    crew_id = getattr(crew, "id", None)
    if crew_id is not None:
        return str(crew_id)
    return None


def _extract_manager_agent_id(crew: Any) -> str | None:
    manager = getattr(crew, "manager_agent", None)
    if manager is None:
        return None
    agent_id = getattr(manager, "id", None)
    if isinstance(agent_id, str) and agent_id:
        return agent_id
    return None


def _is_hierarchical_process(crew: Any) -> bool:
    try:
        module = importlib.import_module("crewai")
        process_cls = getattr(module, "Process", None)
        if process_cls is None:
            return False
        hierarchical = getattr(process_cls, "hierarchical", None)
        return getattr(crew, "process", None) == hierarchical
    except Exception:
        return False


def _set_thread_local_agent_id(agent_id: str | None) -> None:
    _AGENT_CONTEXT.agent_id = agent_id


def _get_thread_local_agent_id() -> str | None:
    agent_id = getattr(_AGENT_CONTEXT, "agent_id", None)
    if isinstance(agent_id, str) and agent_id:
        return agent_id
    return None


def _nonempty_str_agent_id(source: Any) -> str | None:
    """Return ``source["agent_id"]`` when ``source`` is a dict holding a non-empty str."""
    if not isinstance(source, dict):
        return None
    value = source.get("agent_id")
    if isinstance(value, str) and value:
        return value
    return None


def _extract_agent_id_from_inputs(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    direct_agent_id = _nonempty_str_agent_id(kwargs)
    if direct_agent_id is not None:
        return direct_agent_id

    config = kwargs.get("config")
    if isinstance(config, dict):
        nested = _nonempty_str_agent_id(config.get("configurable")) or _nonempty_str_agent_id(config.get("metadata"))
        if nested is not None:
            return nested

    if args:
        return _nonempty_str_agent_id(args[0])

    return None


def _extract_worker_agent_id(task: Any) -> str | None:
    """Extract the worker agent's ID from a CrewAI Task's .agent attribute."""
    agent = getattr(task, "agent", None)
    if agent is None:
        return None
    agent_id = getattr(agent, "id", None)
    if isinstance(agent_id, str) and agent_id:
        return agent_id
    agent_id = getattr(agent, "agent_id", None)
    if isinstance(agent_id, str) and agent_id:
        return agent_id
    return None


def _current_spawn_depth() -> int:
    current = _SPAWN_CTX.get()
    return (current.depth + 1) if current is not None else 1


def _format_blocked_message(reason: str | None) -> str:
    reason_text = reason or "No reason provided."
    return (
        f"[BLOCKED by governance policy] {reason_text}. " "Please choose a different approach to accomplish this task."
    )


def _format_approval_rejected_message(reason: str | None) -> str:
    reason_text = reason or "No reason provided."
    return f"[APPROVAL REJECTED] Action was reviewed and denied: {reason_text}"


_UNKNOWN_DECISION_REASON = "Unrecognized governance decision; denied under enforce."


def _interceptor_enforces(callback_handler: Any) -> bool:
    """Return whether the wired interceptor is in fail-closed ``enforce`` posture.

    The governance interceptor (``RuntimeQueryInterceptor`` /
    ``_FailClosedInterceptor``) carries ``_enforce`` set from
    ``enforcement_mode == "enforce"`` (AAASM-3106). A bare ``GatewayClient`` — used
    when no native runtime authority is engaged — has no such attribute and
    defaults to fail-open. AAASM-3107 reuses this flag so an unknown / malformed
    verdict denies under enforce instead of silently allowing.

    Compared strictly against ``True`` so a stub interceptor whose ``__getattr__``
    synthesizes truthy values for missing attributes is not mistaken for the
    enforce posture; the real flag is always a ``bool``.
    """
    target = getattr(callback_handler, "_interceptor", callback_handler)
    return getattr(target, "_enforce", False) is True


def _unknown_decision(enforce: bool) -> tuple[Literal["allow", "deny", "pending"], str | None]:
    """Map an unrecognized / malformed verdict, failing closed under ``enforce``.

    Under ``enforce`` the SDK is a security control: an unknown, ``None``, or
    malformed verdict must not be silently allowed (AAASM-3107), so it denies.
    Under ``observe`` / ``disabled`` it proceeds (fail open), preserving the
    dry-run / hermetic posture.
    """
    if enforce:
        return "deny", _UNKNOWN_DECISION_REASON
    return "allow", None


_KNOWN_STATUSES: frozenset[str] = frozenset({"allow", "deny", "pending"})


def _coerce_known_status(value: str) -> Literal["allow", "deny", "pending"] | None:
    """Return the verdict literal for a recognized status string, else ``None``."""
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
    enforce = _interceptor_enforces(callback_handler)

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
        status, reason = _normalize_decision(decision, enforce=enforce)
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
            status, reason = _normalize_decision(final_decision, enforce=enforce)

        if status == "deny":
            if is_pending_flow:
                return _format_approval_rejected_message(reason)
            return _format_blocked_message(reason)

        result = original_run(self, *args, **kwargs)
        _record_sync_tool_result(callback_handler, tool_name=str(tool_name), result=result)
        return result

    setattr(base_tool_cls, _ORIGINAL_TOOL_RUN, original_run)
    base_tool_cls.run = patched_run
    setattr(base_tool_cls, _TOOLS_PATCHED_FLAG, True)


def _revert_basetool_run_patch(base_tool_cls: type[Any]) -> None:
    if not getattr(base_tool_cls, _TOOLS_PATCHED_FLAG, False):
        return None

    original_run = getattr(base_tool_cls, _ORIGINAL_TOOL_RUN, None)
    if callable(original_run):
        base_tool_cls.run = original_run

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
        worker_id = _extract_worker_agent_id(self)
        _set_thread_local_agent_id(worker_id or _extract_agent_id_from_inputs(args, kwargs))
        _record_task_start(callback_handler, self)

        spawn_ctx: SpawnContext | None = None
        if worker_id:
            crew = getattr(getattr(self, "agent", None), "crew", None)
            raw_reason = str(getattr(self, "description", "") or "")[:_MAX_DELEGATION_REASON_CHARS]
            spawn_ctx = SpawnContext(
                parent_agent_id=worker_id,
                depth=_current_spawn_depth(),
                spawned_by_tool="crewai_task",
                team_id=_extract_crew_team_id(crew),
                delegation_reason=raw_reason or None,
            )

        try:
            if spawn_ctx is not None:
                with spawn_context_scope(spawn_ctx):
                    result = original_execute_sync(self, *args, **kwargs)
            else:
                result = original_execute_sync(self, *args, **kwargs)
        finally:
            _set_thread_local_agent_id(previous_agent_id)

        _record_task_complete(callback_handler, result)
        return result

    setattr(task_cls, _ORIGINAL_TASK_EXECUTE_SYNC, original_execute_sync)
    task_cls.execute_sync = patched_execute_sync
    setattr(task_cls, _TASK_PATCHED_FLAG, True)


def _revert_task_execute_sync_patch(task_cls: type[Any]) -> None:
    if not getattr(task_cls, _TASK_PATCHED_FLAG, False):
        return None

    original_execute_sync = getattr(task_cls, _ORIGINAL_TASK_EXECUTE_SYNC, None)
    if callable(original_execute_sync):
        task_cls.execute_sync = original_execute_sync

    if hasattr(task_cls, _ORIGINAL_TASK_EXECUTE_SYNC):
        delattr(task_cls, _ORIGINAL_TASK_EXECUTE_SYNC)
    if hasattr(task_cls, _TASK_PATCHED_FLAG):
        delattr(task_cls, _TASK_PATCHED_FLAG)
    return None


def _apply_crew_kickoff_patch(crew_cls: type[Any]) -> None:
    if getattr(crew_cls, _CREW_KICKOFF_PATCHED_FLAG, False):
        return None

    original_kickoff = crew_cls.kickoff

    @wraps(original_kickoff)
    def patched_kickoff(self: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_hierarchical_process(self):
            return original_kickoff(self, *args, **kwargs)

        spawn_ctx = SpawnContext(
            parent_agent_id=_extract_manager_agent_id(self) or "",
            depth=_current_spawn_depth(),
            spawned_by_tool="crewai_kickoff_hierarchical",
            team_id=_extract_crew_team_id(self),
        )
        with spawn_context_scope(spawn_ctx):
            return original_kickoff(self, *args, **kwargs)

    setattr(crew_cls, _ORIGINAL_CREW_KICKOFF, original_kickoff)
    crew_cls.kickoff = patched_kickoff
    setattr(crew_cls, _CREW_KICKOFF_PATCHED_FLAG, True)
    return None


def _revert_crew_kickoff_patch(crew_cls: type[Any]) -> None:
    if not getattr(crew_cls, _CREW_KICKOFF_PATCHED_FLAG, False):
        return None
    original_kickoff = getattr(crew_cls, _ORIGINAL_CREW_KICKOFF, None)
    if callable(original_kickoff):
        crew_cls.kickoff = original_kickoff
    for attr in (_ORIGINAL_CREW_KICKOFF, _CREW_KICKOFF_PATCHED_FLAG):
        if hasattr(crew_cls, attr):
            delattr(crew_cls, attr)
    return None
