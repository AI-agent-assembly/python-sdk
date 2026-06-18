from types import SimpleNamespace

import pytest

from agent_assembly.adapters import FrameworkAdapter, GovernanceInterceptor
from agent_assembly.exceptions import AdapterValidationError


class IncompleteAdapter(FrameworkAdapter):
    def get_framework_name(self) -> str:
        return "math"


def test_framework_adapter_requires_all_abstract_methods() -> None:
    with pytest.raises(TypeError):
        IncompleteAdapter()  # type: ignore[abstract]  # deliberately instantiate abstract class to assert TypeError


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


class InvalidRegistrationAdapter(FrameworkAdapter):
    def get_framework_name(self) -> str:
        return "   "

    def get_supported_versions(self) -> list[str]:
        return []

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        return None

    def unregister_hooks(self) -> None:
        return None


def test_register_raises_validation_error_for_invalid_contract() -> None:
    with pytest.raises(AdapterValidationError):
        InvalidRegistrationAdapter().register(object())


class EmptyVersionsAdapter(FrameworkAdapter):
    def get_framework_name(self) -> str:
        return "math"

    def get_supported_versions(self) -> list[str]:
        return []

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        return None

    def unregister_hooks(self) -> None:
        return None


def test_validate_registration_rejects_empty_supported_versions() -> None:
    with pytest.raises(AdapterValidationError, match="supported versions must not be empty"):
        EmptyVersionsAdapter().validate_registration()


class BlankVersionRangeAdapter(FrameworkAdapter):
    def get_framework_name(self) -> str:
        return "math"

    def get_supported_versions(self) -> list[str]:
        return ["   "]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        return None

    def unregister_hooks(self) -> None:
        return None


def test_validate_registration_rejects_blank_version_range() -> None:
    with pytest.raises(AdapterValidationError, match="version ranges must be non-empty"):
        BlankVersionRangeAdapter().validate_registration()


class AgentIdAwareAdapter(FrameworkAdapter):
    def __init__(self) -> None:
        self.process_agent_id: str | None = None

    def get_framework_name(self) -> str:
        return "math"

    def get_supported_versions(self) -> list[str]:
        return [">=0.1.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        return None

    def unregister_hooks(self) -> None:
        return None


def test_set_process_agent_id_sets_attribute_when_supported() -> None:
    adapter = AgentIdAwareAdapter()
    adapter.set_process_agent_id("proc-7")
    assert adapter.process_agent_id == "proc-7"


def test_set_process_agent_id_is_noop_when_attribute_absent() -> None:
    # NonVersionedFrameworkAdapter has no process_agent_id attribute; the
    # base no-op must not raise.
    adapter = NonVersionedFrameworkAdapter()
    adapter.set_process_agent_id("ignored")
    assert not hasattr(adapter, "process_agent_id")


class ValidRegistrationAdapter(FrameworkAdapter):
    def __init__(self) -> None:
        self.hooks_registered = False

    def get_framework_name(self) -> str:
        return "pytest"

    def get_supported_versions(self) -> list[str]:
        return [">=8.0.0,<9.0.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        self.hooks_registered = True

    def unregister_hooks(self) -> None:
        return None


def test_register_calls_register_hooks_when_contract_is_valid() -> None:
    adapter = ValidRegistrationAdapter()
    adapter.register(object())
    assert adapter.hooks_registered is True


class LangChainFrameworkAdapter(FrameworkAdapter):
    def get_framework_name(self) -> str:
        return "langchain"

    def get_supported_versions(self) -> list[str]:
        return [">=0.1.0,<0.4.0"]

    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:
        return None

    def unregister_hooks(self) -> None:
        return None


def test_is_available_returns_true_for_langchain(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_import_module(module_name: str) -> object:
        calls.append(module_name)
        if module_name == "langchain":
            return SimpleNamespace(__version__="0.3.0")
        raise ImportError

    monkeypatch.setattr("agent_assembly.adapters.base.importlib.import_module", fake_import_module)

    adapter = LangChainFrameworkAdapter()
    assert adapter.is_available() is True
    assert calls == ["langchain"]


def test_get_active_version_returns_langchain_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_import_module(module_name: str) -> object:
        if module_name == "langchain":
            return SimpleNamespace(__version__="0.3.0")
        raise ImportError

    monkeypatch.setattr("agent_assembly.adapters.base.importlib.import_module", fake_import_module)

    assert LangChainFrameworkAdapter().get_active_version() == "0.3.0"
