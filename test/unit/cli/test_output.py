"""Unit tests for output formatting."""

from __future__ import annotations

from agent_assembly.cli.adapter_validator import AdapterValidationResult
from agent_assembly.cli.output import format_results


class TestFormatResults:
    """Tests for format_results."""

    def test_all_pass_output(self) -> None:
        results = [
            AdapterValidationResult(check_name="check_a", passed=True, message="ok"),
            AdapterValidationResult(check_name="check_b", passed=True, message="ok"),
        ]
        output = format_results(results)
        assert "[PASS]" in output
        assert "[FAIL]" not in output
        assert "2 passed, 0 failed" in output

    def test_mixed_output(self) -> None:
        results = [
            AdapterValidationResult(check_name="check_a", passed=True, message="ok"),
            AdapterValidationResult(
                check_name="check_b", passed=False, message="bad"
            ),
        ]
        output = format_results(results)
        assert "[PASS]" in output
        assert "[FAIL]" in output
        assert "1 passed, 1 failed" in output

    def test_pass_fail_prefix_format(self) -> None:
        results = [
            AdapterValidationResult(check_name="my_check", passed=True, message="m"),
        ]
        output = format_results(results)
        assert "  [PASS] my_check: m" in output
