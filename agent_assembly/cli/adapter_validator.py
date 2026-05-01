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


def _check_inherits_framework_adapter(cls: type) -> AdapterValidationResult:
    """Check that the class inherits from FrameworkAdapter."""
    if issubclass(cls, FrameworkAdapter):
        return AdapterValidationResult(
            check_name="inherits_framework_adapter",
            passed=True,
            message="Class inherits from FrameworkAdapter.",
        )
    return AdapterValidationResult(
        check_name="inherits_framework_adapter",
        passed=False,
        message=f"Class {cls.__name__} does not inherit from FrameworkAdapter.",
    )


_REQUIRED_ABSTRACT_METHODS = frozenset(
    {
        "get_framework_name",
        "get_supported_versions",
        "register_hooks",
        "unregister_hooks",
    }
)


def _check_abstract_methods_implemented(cls: type) -> AdapterValidationResult:
    """Check that all 4 required abstract methods are concretely implemented."""
    remaining = getattr(cls, "__abstractmethods__", frozenset())
    missing = _REQUIRED_ABSTRACT_METHODS & remaining
    if not missing:
        return AdapterValidationResult(
            check_name="abstract_methods_implemented",
            passed=True,
            message="All required abstract methods are implemented.",
        )
    return AdapterValidationResult(
        check_name="abstract_methods_implemented",
        passed=False,
        message=f"Missing implementations: {', '.join(sorted(missing))}.",
    )
