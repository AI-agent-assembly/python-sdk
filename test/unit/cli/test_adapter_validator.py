"""Unit tests for adapter validator logic."""

from __future__ import annotations

from agent_assembly.adapters.base import FrameworkAdapter
from agent_assembly.cli.adapter_validator import (
    AdapterValidationResult,
    _check_abstract_methods_implemented,
    _check_entry_point_metadata,
    _check_framework_name,
    _check_inherits_framework_adapter,
    _check_register_hooks_signature,
    _check_supported_versions,
    _check_unregister_hooks_idempotent,
    validate_adapter,
)


class TestAdapterValidationResult:
    """Tests for the AdapterValidationResult dataclass."""

    def test_fields_stored(self) -> None:
        result = AdapterValidationResult(check_name="test_check", passed=True, message="ok")
        assert result.check_name == "test_check"
        assert result.passed is True
        assert result.message == "ok"

    def test_equality(self) -> None:
        a = AdapterValidationResult(check_name="c", passed=True, message="m")
        b = AdapterValidationResult(check_name="c", passed=True, message="m")
        assert a == b

    def test_frozen(self) -> None:
        import pytest

        result = AdapterValidationResult(check_name="c", passed=True, message="m")
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


class TestCheckFrameworkName:
    """Tests for _check_framework_name."""

    def test_non_empty_name_passes(self, valid_adapter_cls: type) -> None:
        result = _check_framework_name(valid_adapter_cls())
        assert result.passed is True
        assert "test_framework" in result.message

    def test_empty_name_fails(self, empty_name_adapter_cls: type) -> None:
        result = _check_framework_name(empty_name_adapter_cls())
        assert result.passed is False
        assert "non-empty string" in result.message

    def test_whitespace_name_fails(self) -> None:
        from test.unit.cli.conftest import ValidAdapter

        class WhitespaceAdapter(ValidAdapter):
            def get_framework_name(self) -> str:
                return "   "

        result = _check_framework_name(WhitespaceAdapter())
        assert result.passed is False


class TestCheckSupportedVersions:
    """Tests for _check_supported_versions."""

    def test_valid_list_passes(self, valid_adapter_cls: type) -> None:
        result = _check_supported_versions(valid_adapter_cls())
        assert result.passed is True

    def test_empty_list_fails(self, empty_versions_adapter_cls: type) -> None:
        result = _check_supported_versions(empty_versions_adapter_cls())
        assert result.passed is False
        assert "non-empty list" in result.message

    def test_empty_string_in_list_fails(self) -> None:
        from test.unit.cli.conftest import ValidAdapter

        class EmptyStringVersionAdapter(ValidAdapter):
            def get_supported_versions(self) -> list[str]:
                return [">=1.0.0", ""]

        result = _check_supported_versions(EmptyStringVersionAdapter())
        assert result.passed is False
        assert "index 1" in result.message


class TestCheckRegisterHooksSignature:
    """Tests for _check_register_hooks_signature."""

    def test_correct_signature_passes(self, valid_adapter_cls: type) -> None:
        result = _check_register_hooks_signature(valid_adapter_cls)
        assert result.passed is True

    def test_missing_param_fails(self) -> None:
        from test.unit.cli.conftest import ValidAdapter

        class NoParamAdapter(ValidAdapter):
            def register_hooks(self) -> None:  # type: ignore[override]
                pass

        result = _check_register_hooks_signature(NoParamAdapter)
        assert result.passed is False
        assert "must accept" in result.message


class TestCheckUnregisterHooksIdempotent:
    """Tests for _check_unregister_hooks_idempotent."""

    def test_double_call_no_raise_passes(self, valid_adapter_cls: type) -> None:
        result = _check_unregister_hooks_idempotent(valid_adapter_cls())
        assert result.passed is True

    def test_raises_on_second_call_fails(self, non_idempotent_adapter_cls: type) -> None:
        result = _check_unregister_hooks_idempotent(non_idempotent_adapter_cls())
        assert result.passed is False
        assert "not idempotent" in result.message


class TestCheckEntryPointMetadata:
    """Tests for _check_entry_point_metadata."""

    def test_valid_pyproject_passes(self, valid_adapter_cls: type, tmp_path: object) -> None:
        import pathlib

        assert isinstance(tmp_path, pathlib.Path)
        pyproject = tmp_path / "pyproject.toml"
        qualname = f"{valid_adapter_cls.__module__}:{valid_adapter_cls.__qualname__}"
        pyproject.write_text(f'[project.entry-points."agent_assembly.adapters"]\n' f'test_framework = "{qualname}"\n')
        result = _check_entry_point_metadata(valid_adapter_cls, str(tmp_path))
        assert result.passed is True

    def test_missing_entry_point_fails(self, valid_adapter_cls: type, tmp_path: object) -> None:
        import pathlib

        assert isinstance(tmp_path, pathlib.Path)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\nname = 'test'\n")
        result = _check_entry_point_metadata(valid_adapter_cls, str(tmp_path))
        assert result.passed is False
        assert "missing" in result.message

    def test_no_pyproject_skips(self, valid_adapter_cls: type, tmp_path: object) -> None:
        import pathlib

        assert isinstance(tmp_path, pathlib.Path)
        result = _check_entry_point_metadata(valid_adapter_cls, str(tmp_path))
        assert result.passed is True
        assert "skipping" in result.message.lower()


class TestValidateAdapter:
    """Tests for validate_adapter orchestrator."""

    def test_all_pass_for_valid_adapter(self, valid_adapter_cls: type) -> None:
        results = validate_adapter(valid_adapter_cls, "test.module")
        assert all(r.passed for r in results)

    def test_mixed_fail_for_empty_name(self, empty_name_adapter_cls: type) -> None:
        results = validate_adapter(empty_name_adapter_cls, "test.module")
        failed = [r for r in results if not r.passed]
        assert len(failed) >= 1
        assert any(r.check_name == "framework_name" for r in failed)

    def test_short_circuits_on_inheritance_failure(self, not_an_adapter_cls: type) -> None:
        results = validate_adapter(not_an_adapter_cls, "test.module")
        assert len(results) == 2
        assert not results[0].passed

    def test_result_count_for_valid_adapter(self, valid_adapter_cls: type) -> None:
        results = validate_adapter(valid_adapter_cls, "test.module")
        assert len(results) == 7
