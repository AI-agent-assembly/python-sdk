"""OpenAI Agents patch module."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from typing import Any


@dataclass(slots=True)
class OpenAIAgentsPatch:
    """Patch placeholder for OpenAI Agents SDK interception."""

    callback_handler: Any

    def apply(self) -> bool:
        _ = self.callback_handler
        return _is_openai_agents_available()

    def revert(self) -> None:
        return None


def _is_openai_agents_available() -> bool:
    return importlib.util.find_spec("openai.agents") is not None
