from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Literal

from agent_assembly.adapters.base import FrameworkAdapter


@dataclass(frozen=True, slots=True)
class AdapterInfo:
    name: str
    version: str
    status: Literal["active", "error"]
    hooks_registered: int


class AdapterRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._registered: dict[str, FrameworkAdapter] = {}
        self._active: dict[str, FrameworkAdapter] = {}
