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
