"""Adapter contract validation logic for community adapters."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import tomllib
from dataclasses import dataclass
from pathlib import Path
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
    remaining: frozenset[str] = getattr(cls, "__abstractmethods__", frozenset())
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


def _check_register_hooks_signature(cls: type) -> AdapterValidationResult:
    """Check that register_hooks accepts a GovernanceInterceptor argument."""
    register_hooks = getattr(cls, "register_hooks")
    sig = inspect.signature(register_hooks)
    params = [p for name, p in sig.parameters.items() if name != "self"]
    if not params:
        return AdapterValidationResult(
            check_name="register_hooks_signature",
            passed=False,
            message="register_hooks() must accept an interceptor argument.",
        )
    first_param = params[0]
    annotation = first_param.annotation
    acceptable = (
        annotation is inspect.Parameter.empty
        or annotation is GovernanceInterceptor
        or (isinstance(annotation, str) and "GovernanceInterceptor" in annotation)
    )
    if acceptable:
        return AdapterValidationResult(
            check_name="register_hooks_signature",
            passed=True,
            message="register_hooks() accepts an interceptor argument.",
        )
    return AdapterValidationResult(
        check_name="register_hooks_signature",
        passed=False,
        message=(f"register_hooks() first parameter annotated as {annotation}, " f"expected GovernanceInterceptor."),
    )


def _check_unregister_hooks_idempotent(
    instance: FrameworkAdapter,
) -> AdapterValidationResult:
    """Check that calling unregister_hooks() twice does not raise."""
    try:
        instance.unregister_hooks()
        instance.unregister_hooks()
    except Exception as exc:
        return AdapterValidationResult(
            check_name="unregister_hooks_idempotent",
            passed=False,
            message=(f"unregister_hooks() is not idempotent: " f"second call raised {type(exc).__name__}: {exc}"),
        )
    return AdapterValidationResult(
        check_name="unregister_hooks_idempotent",
        passed=True,
        message="unregister_hooks() is idempotent (two calls without error).",
    )


def _check_entry_point_metadata(cls: type, path_or_module: str) -> AdapterValidationResult:
    """Check entry point metadata in pyproject.toml if present at the given path."""
    search_path = Path(path_or_module)
    if search_path.is_file():
        search_path = search_path.parent

    pyproject_path = search_path / "pyproject.toml"
    if not pyproject_path.is_file():
        return AdapterValidationResult(
            check_name="entry_point_metadata",
            passed=True,
            message="No pyproject.toml found; skipping entry point check.",
        )

    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        return AdapterValidationResult(
            check_name="entry_point_metadata",
            passed=False,
            message=f"Failed to parse pyproject.toml: {exc}",
        )

    entry_points = data.get("project", {}).get("entry-points", {}).get("agent_assembly.adapters", {})
    if not entry_points:
        return AdapterValidationResult(
            check_name="entry_point_metadata",
            passed=False,
            message=('pyproject.toml missing [project.entry-points."agent_assembly.adapters"] ' "section."),
        )

    class_qualname = f"{cls.__module__}:{cls.__qualname__}"
    for ep_name, ep_value in entry_points.items():
        if ep_value == class_qualname:
            return AdapterValidationResult(
                check_name="entry_point_metadata",
                passed=True,
                message=f"Entry point '{ep_name}' correctly references {class_qualname}.",
            )

    return AdapterValidationResult(
        check_name="entry_point_metadata",
        passed=False,
        message=(f"No entry point references {class_qualname}. " f"Found: {entry_points}."),
    )


def validate_adapter(cls: type, path_or_module: str) -> list[AdapterValidationResult]:
    """Run all contract checks against an adapter class and return results."""
    results: list[AdapterValidationResult] = []

    results.append(_check_inherits_framework_adapter(cls))
    results.append(_check_abstract_methods_implemented(cls))

    # Instance-level checks require a concrete class that can be instantiated
    if any(not r.passed for r in results):
        return results

    instance = cls()
    results.append(_check_framework_name(instance))
    results.append(_check_supported_versions(instance))
    results.append(_check_register_hooks_signature(cls))
    results.append(_check_unregister_hooks_idempotent(instance))
    results.append(_check_entry_point_metadata(cls, path_or_module))

    return results


def _find_adapter_class_in_module(module: object) -> type | None:
    """Scan a module for the first FrameworkAdapter subclass."""
    for _name, obj in inspect.getmembers(module, inspect.isclass):
        if obj is not FrameworkAdapter and issubclass(obj, FrameworkAdapter):
            return obj
    return None


def load_adapter_class_from_module(module_name: str) -> type:
    """Load an adapter class from a dotted module name.

    Raises:
        ImportError: If the module cannot be imported.
        ValueError: If no FrameworkAdapter subclass is found in the module.
    """
    module = importlib.import_module(module_name)
    cls = _find_adapter_class_in_module(module)
    if cls is None:
        raise ValueError(f"No FrameworkAdapter subclass found in module '{module_name}'.")
    return cls


def load_adapter_class_from_path(file_path: str) -> type:
    """Load an adapter class from a file system path.

    Raises:
        FileNotFoundError: If the path does not exist.
        ValueError: If no FrameworkAdapter subclass is found in the file.
    """
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    module_name = f"_aasm_validate_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot create module spec from path: {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    cls = _find_adapter_class_in_module(module)
    if cls is None:
        raise ValueError(f"No FrameworkAdapter subclass found in '{path}'.")
    return cls


def load_adapter_class(path_or_module: str) -> type:
    """Load an adapter class from either a file path or a dotted module name."""
    candidate = Path(path_or_module)
    if candidate.exists():
        return load_adapter_class_from_path(path_or_module)
    return load_adapter_class_from_module(path_or_module)
