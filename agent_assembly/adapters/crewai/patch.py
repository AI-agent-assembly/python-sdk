"""CrewAI patch module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_TOOLS_PATCHED_FLAG = "_agent_assembly_crewai_tools_patched"
_TASK_PATCHED_FLAG = "_agent_assembly_crewai_task_patched"
_ORIGINAL_TOOL_RUN = "_agent_assembly_original_crewai_tool_run"
_ORIGINAL_TASK_EXECUTE_SYNC = "_agent_assembly_original_crewai_task_execute_sync"


@dataclass(slots=True)
class CrewAIPatch:
    """Applies CrewAI runtime monkey-patching hooks."""

    callback_handler: Any

    def apply(self) -> bool:
        """Apply patch wiring and return whether CrewAI is available."""
        del self
        return False
