"""Unit tests for adapter validator logic."""

from __future__ import annotations

from agent_assembly.cli.adapter_validator import AdapterValidationResult


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
