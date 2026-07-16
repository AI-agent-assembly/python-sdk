"""Unit tests for adapter class loader functions."""

from __future__ import annotations

import pytest

from agent_assembly.cli.adapter_validator import (
    load_adapter_class,
    load_adapter_class_from_module,
    load_adapter_class_from_path,
)


class TestLoadAdapterClassFromModule:
    """Tests for load_adapter_class_from_module."""

    def test_valid_module(self) -> None:
        cls = load_adapter_class_from_module("agent_assembly.adapters.langchain.adapter")
        from agent_assembly.adapters.base import FrameworkAdapter

        assert issubclass(cls, FrameworkAdapter)

    def test_invalid_module_raises(self) -> None:
        with pytest.raises(ImportError):
            load_adapter_class_from_module("nonexistent.module.path")

    def test_module_with_no_adapter_raises(self) -> None:
        with pytest.raises(ValueError, match="No FrameworkAdapter subclass"):
            load_adapter_class_from_module("agent_assembly.exceptions")


class TestLoadAdapterClassFromPath:
    """Tests for load_adapter_class_from_path."""

    def test_valid_file_path(self, tmp_path: object) -> None:
        import pathlib

        assert isinstance(tmp_path, pathlib.Path)
        adapter_file = tmp_path / "my_adapter.py"
        adapter_file.write_text(
            "from agent_assembly.adapters.base import FrameworkAdapter, GovernanceInterceptor\n"
            "\n"
            "class MyAdapter(FrameworkAdapter):\n"
            "    def get_framework_name(self) -> str:\n"
            "        return 'my_framework'\n"
            "    def get_supported_versions(self) -> list[str]:\n"
            "        return ['>=1.0.0']\n"
            "    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:\n"
            "        pass\n"
            "    def unregister_hooks(self) -> None:\n"
            "        pass\n"
        )
        cls = load_adapter_class_from_path(str(adapter_file))
        from agent_assembly.adapters.base import FrameworkAdapter

        assert issubclass(cls, FrameworkAdapter)

    def test_invalid_path_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_adapter_class_from_path("/nonexistent/path/adapter.py")

    def test_file_with_no_adapter_raises(self, tmp_path: object) -> None:
        import pathlib

        assert isinstance(tmp_path, pathlib.Path)
        empty_file = tmp_path / "empty.py"
        empty_file.write_text("x = 1\n")
        path = str(empty_file)
        with pytest.raises(ValueError, match="No FrameworkAdapter subclass"):
            load_adapter_class_from_path(path)


class TestLoadAdapterClass:
    """Tests for load_adapter_class dispatcher."""

    def test_dispatches_to_path_for_existing_file(self, tmp_path: object) -> None:
        import pathlib

        assert isinstance(tmp_path, pathlib.Path)
        adapter_file = tmp_path / "my_adapter.py"
        adapter_file.write_text(
            "from agent_assembly.adapters.base import FrameworkAdapter, GovernanceInterceptor\n"
            "\n"
            "class MyAdapter(FrameworkAdapter):\n"
            "    def get_framework_name(self) -> str:\n"
            "        return 'my_framework'\n"
            "    def get_supported_versions(self) -> list[str]:\n"
            "        return ['>=1.0.0']\n"
            "    def register_hooks(self, interceptor: GovernanceInterceptor) -> None:\n"
            "        pass\n"
            "    def unregister_hooks(self) -> None:\n"
            "        pass\n"
        )
        cls = load_adapter_class(str(adapter_file))
        assert cls.__name__ == "MyAdapter"

    def test_dispatches_to_module_for_dotted_name(self) -> None:
        cls = load_adapter_class("agent_assembly.adapters.langchain.adapter")
        from agent_assembly.adapters.base import FrameworkAdapter

        assert issubclass(cls, FrameworkAdapter)
