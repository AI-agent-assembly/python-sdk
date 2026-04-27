import pytest

from agent_assembly.adapters import FrameworkAdapter, GovernanceInterceptor


class IncompleteAdapter(FrameworkAdapter):
    def get_framework_name(self) -> str:
        return "math"


def test_framework_adapter_requires_all_abstract_methods() -> None:
    with pytest.raises(TypeError):
        IncompleteAdapter()


class AvailableFrameworkAdapter(FrameworkAdapter):
    def get_framework_name(self) -> str:
        return "math"

    def get_supported_versions(self) -> list[str]:
        return []

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        return None

    def unregister_hooks(self) -> None:
        return None


def test_is_available_returns_true_when_framework_exists() -> None:
    assert AvailableFrameworkAdapter().is_available() is True


class MissingFrameworkAdapter(FrameworkAdapter):
    def get_framework_name(self) -> str:
        return "_agent_assembly_missing_framework_"

    def get_supported_versions(self) -> list[str]:
        return []

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        return None

    def unregister_hooks(self) -> None:
        return None


def test_is_available_returns_false_when_framework_is_missing() -> None:
    assert MissingFrameworkAdapter().is_available() is False


class VersionedFrameworkAdapter(FrameworkAdapter):
    def get_framework_name(self) -> str:
        return "pytest"

    def get_supported_versions(self) -> list[str]:
        return []

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        return None

    def unregister_hooks(self) -> None:
        return None


def test_get_active_version_returns_module_version() -> None:
    assert VersionedFrameworkAdapter().get_active_version() is not None


class NonVersionedFrameworkAdapter(FrameworkAdapter):
    def get_framework_name(self) -> str:
        return "math"

    def get_supported_versions(self) -> list[str]:
        return []

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        return None

    def unregister_hooks(self) -> None:
        return None


def test_get_active_version_returns_none_without_version() -> None:
    assert NonVersionedFrameworkAdapter().get_active_version() is None
