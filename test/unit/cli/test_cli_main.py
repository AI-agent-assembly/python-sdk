"""Unit tests for CLI main entry point."""

from __future__ import annotations

from unittest import mock

import pytest

from agent_assembly.cli.main import main


class TestCliMainExitCodeZero:
    """Tests for CLI main returning exit code 0."""

    def test_valid_adapter_exits_zero(self) -> None:
        with mock.patch(
            "sys.argv",
            ["aasm", "adapter", "validate", "agent_assembly.adapters.langchain.adapter"],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0


class TestCliMainExitCodeOne:
    """Tests for CLI main returning exit code 1."""

    def test_nonexistent_module_exits_one(self) -> None:
        with mock.patch(
            "sys.argv",
            ["aasm", "adapter", "validate", "nonexistent.module"],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_no_command_exits_one(self) -> None:
        with mock.patch("sys.argv", ["aasm"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
