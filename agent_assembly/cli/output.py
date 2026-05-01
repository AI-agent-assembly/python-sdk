"""Pass/fail output formatting for adapter validation results."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_assembly.cli.adapter_validator import AdapterValidationResult


def format_results(results: list[AdapterValidationResult]) -> str:
    """Format validation results as human-readable PASS/FAIL lines."""
    lines: list[str] = []
    for result in results:
        prefix = "PASS" if result.passed else "FAIL"
        lines.append(f"  [{prefix}] {result.check_name}: {result.message}")

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    lines.append("")
    lines.append(f"Results: {passed} passed, {failed} failed, {len(results)} total")

    return "\n".join(lines)
