"""CrewAI patch module."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from threading import local
from typing import Any, Literal, Mapping

_TOOLS_PATCHED_FLAG = "_agent_assembly_crewai_tools_patched"
_TASK_PATCHED_FLAG = "_agent_assembly_crewai_task_patched"
_ORIGINAL_TOOL_RUN = "_agent_assembly_original_crewai_tool_run"
_ORIGINAL_TASK_EXECUTE_SYNC = "_agent_assembly_original_crewai_task_execute_sync"
_AGENT_CONTEXT = local()


@dataclass(slots=True)
class CrewAIPatch:
    """Applies CrewAI runtime monkey-patching hooks."""

    callback_handler: Any

    def apply(self) -> bool:
        """Apply patch wiring and return whether CrewAI is available."""
        del self
        return False


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
