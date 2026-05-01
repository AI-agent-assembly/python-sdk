"""Unit tests for adapter class loader functions."""

from __future__ import annotations

import pytest

from agent_assembly.cli.adapter_validator import load_adapter_class_from_module


class TestLoadAdapterClassFromModule:
    """Tests for load_adapter_class_from_module."""

    def test_valid_module(self) -> None:
        cls = load_adapter_class_from_module(
            "agent_assembly.adapters.langchain.adapter"
        )
        from agent_assembly.adapters.base import FrameworkAdapter

        assert issubclass(cls, FrameworkAdapter)

    def test_invalid_module_raises(self) -> None:
        with pytest.raises(ImportError):
            load_adapter_class_from_module("nonexistent.module.path")

    def test_module_with_no_adapter_raises(self) -> None:
        with pytest.raises(ValueError, match="No FrameworkAdapter subclass"):
            load_adapter_class_from_module("agent_assembly.exceptions")
