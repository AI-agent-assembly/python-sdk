from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class AdapterInfo:
    name: str
    version: str
    status: Literal["active", "error"]
    hooks_registered: int
