"""Shared fixtures for CLI adapter validator tests."""

from __future__ import annotations

import pytest

from agent_assembly.adapters.base import FrameworkAdapter, GovernanceInterceptor


class ValidAdapter(FrameworkAdapter):
    """A fully valid adapter for testing."""

    def get_framework_name(self) -> str:
        return "test_framework"

    def get_supported_versions(self) -> list[str]:
        return [">=1.0.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        pass

    def unregister_hooks(self) -> None:
        pass


class EmptyNameAdapter(FrameworkAdapter):
    """Adapter that returns an empty framework name."""

    def get_framework_name(self) -> str:
        return ""

    def get_supported_versions(self) -> list[str]:
        return [">=1.0.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        pass

    def unregister_hooks(self) -> None:
        pass


class EmptyVersionsAdapter(FrameworkAdapter):
    """Adapter that returns an empty versions list."""

    def get_framework_name(self) -> str:
        return "test_framework"

    def get_supported_versions(self) -> list[str]:
        return []

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        pass

    def unregister_hooks(self) -> None:
        pass


class NonIdempotentAdapter(FrameworkAdapter):
    """Adapter whose unregister_hooks raises on the second call."""

    def __init__(self) -> None:
        self._call_count = 0

    def get_framework_name(self) -> str:
        return "test_framework"

    def get_supported_versions(self) -> list[str]:
        return [">=1.0.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        pass

    def unregister_hooks(self) -> None:
        self._call_count += 1
        if self._call_count > 1:
            raise RuntimeError("Already unregistered")


class NotAnAdapter:
    """A class that does not inherit from FrameworkAdapter."""


@pytest.fixture()
def valid_adapter_cls() -> type:
    return ValidAdapter


@pytest.fixture()
def empty_name_adapter_cls() -> type:
    return EmptyNameAdapter


@pytest.fixture()
def empty_versions_adapter_cls() -> type:
    return EmptyVersionsAdapter


@pytest.fixture()
def non_idempotent_adapter_cls() -> type:
    return NonIdempotentAdapter


@pytest.fixture()
def not_an_adapter_cls() -> type:
    return NotAnAdapter
