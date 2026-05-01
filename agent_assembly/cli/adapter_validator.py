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


def _check_framework_name(instance: FrameworkAdapter) -> AdapterValidationResult:
    """Check that get_framework_name() returns a non-empty string."""
    try:
        name = instance.get_framework_name()
    except Exception as exc:
        return AdapterValidationResult(
            check_name="framework_name",
            passed=False,
            message=f"get_framework_name() raised {type(exc).__name__}: {exc}",
        )
    if isinstance(name, str) and name.strip():
        return AdapterValidationResult(
            check_name="framework_name",
            passed=True,
            message=f"Framework name: '{name}'.",
        )
    return AdapterValidationResult(
        check_name="framework_name",
        passed=False,
        message="get_framework_name() must return a non-empty string.",
    )


def _check_supported_versions(instance: FrameworkAdapter) -> AdapterValidationResult:
    """Check that get_supported_versions() returns a non-empty list of strings."""
    try:
        versions = instance.get_supported_versions()
    except Exception as exc:
        return AdapterValidationResult(
            check_name="supported_versions",
            passed=False,
            message=f"get_supported_versions() raised {type(exc).__name__}: {exc}",
        )
    if not isinstance(versions, list) or not versions:
        return AdapterValidationResult(
            check_name="supported_versions",
            passed=False,
            message="get_supported_versions() must return a non-empty list.",
        )
    for i, v in enumerate(versions):
        if not isinstance(v, str) or not v.strip():
            return AdapterValidationResult(
                check_name="supported_versions",
                passed=False,
                message=f"Version at index {i} must be a non-empty string.",
            )
    return AdapterValidationResult(
        check_name="supported_versions",
        passed=True,
        message=f"Supported versions: {versions}.",
    )
