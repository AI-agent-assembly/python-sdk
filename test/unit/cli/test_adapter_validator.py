"""Unit tests for adapter validator logic."""

from __future__ import annotations

from agent_assembly.cli.adapter_validator import (
    AdapterValidationResult,
    _check_abstract_methods_implemented,
    _check_inherits_framework_adapter,
)
from agent_assembly.adapters.base import FrameworkAdapter


class TestAdapterValidationResult:
    """Tests for the AdapterValidationResult dataclass."""

    def test_fields_stored(self) -> None:
        result = AdapterValidationResult(
            check_name="test_check", passed=True, message="ok"
        )
        assert result.check_name == "test_check"
        assert result.passed is True
        assert result.message == "ok"

    def test_equality(self) -> None:
        a = AdapterValidationResult(check_name="c", passed=True, message="m")
        b = AdapterValidationResult(check_name="c", passed=True, message="m")
        assert a == b

    def test_frozen(self) -> None:
        import pytest

        result = AdapterValidationResult(
            check_name="c", passed=True, message="m"
        )
        with pytest.raises(AttributeError):
            result.passed = False  # type: ignore[misc]


class TestCheckInheritsFrameworkAdapter:
    """Tests for _check_inherits_framework_adapter."""

    def test_valid_subclass_passes(self, valid_adapter_cls: type) -> None:
        result = _check_inherits_framework_adapter(valid_adapter_cls)
        assert result.passed is True
        assert result.check_name == "inherits_framework_adapter"

    def test_non_subclass_fails(self, not_an_adapter_cls: type) -> None:
        result = _check_inherits_framework_adapter(not_an_adapter_cls)
        assert result.passed is False
        assert "does not inherit" in result.message


class TestCheckAbstractMethodsImplemented:
    """Tests for _check_abstract_methods_implemented."""

    def test_all_methods_concrete_passes(self, valid_adapter_cls: type) -> None:
        result = _check_abstract_methods_implemented(valid_adapter_cls)
        assert result.passed is True

    def test_missing_method_fails(self) -> None:
        class PartialAdapter(FrameworkAdapter):
            def get_framework_name(self) -> str:
                return "test"

            def get_supported_versions(self) -> list[str]:
                return [">=1.0.0"]

        result = _check_abstract_methods_implemented(PartialAdapter)
        assert result.passed is False
        assert "register_hooks" in result.message
        assert "unregister_hooks" in result.message
