"""CrewAI patch module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CrewAIPatch:
    """Applies CrewAI runtime monkey-patching hooks."""

    callback_handler: Any

    def apply(self) -> bool:
        """Apply patch wiring and return whether CrewAI is available."""
        del self
        return False
