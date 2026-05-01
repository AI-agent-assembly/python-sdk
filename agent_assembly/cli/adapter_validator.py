"""Adapter contract validation logic for community adapters."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from agent_assembly.adapters.base import FrameworkAdapter, GovernanceInterceptor
