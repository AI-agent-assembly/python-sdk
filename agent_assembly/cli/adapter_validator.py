"""Adapter contract validation logic for community adapters."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from agent_assembly.adapters.base import FrameworkAdapter, GovernanceInterceptor


@dataclass(frozen=True, slots=True)
class AdapterValidationResult:
    """Result of a single adapter contract check."""

    check_name: str
    passed: bool
    message: str
