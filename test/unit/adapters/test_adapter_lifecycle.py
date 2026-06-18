"""Lifecycle tests for the concrete `FrameworkAdapter` subclasses.

Each adapter delegates `register_hooks` / `unregister_hooks` to a framework
`*Patch` object's `apply()` / `revert()`. These tests substitute a fake Patch
so the adapter's own delegation, idempotent teardown, and metadata accessors
are exercised without importing the real frameworks (which are not installed).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_assembly.adapters.crewai.adapter import CrewAIAdapter
from agent_assembly.adapters.google_adk.adapter import GoogleADKAdapter
from agent_assembly.adapters.langchain.adapter import LangChainAdapter
from agent_assembly.adapters.langgraph.adapter import LangGraphAdapter
from agent_assembly.adapters.mcp.adapter import MCPAdapter
from agent_assembly.adapters.openai_agents.adapter import OpenAIAgentsAdapter
from agent_assembly.adapters.pydantic_ai.adapter import PydanticAIAdapter


class _FakePatch:
    """Stands in for a framework Patch; records apply/revert."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.applied = 0
        self.reverted = 0

    def apply(self) -> None:
        self.applied += 1

    def revert(self) -> None:
        self.reverted += 1


def test_crewai_adapter_metadata() -> None:
    adapter = CrewAIAdapter()
    assert adapter.get_framework_name() == "crewai"
    assert adapter.get_supported_versions() == [">=0.1.0"]


def test_crewai_adapter_register_then_unregister(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent_assembly.adapters.crewai.adapter.CrewAIPatch", _FakePatch)
    adapter = CrewAIAdapter()

    adapter.register_hooks(MagicMock())
    patch_obj = adapter._patch
    assert isinstance(patch_obj, _FakePatch)
    assert patch_obj.applied == 1

    adapter.unregister_hooks()
    assert patch_obj.reverted == 1
    assert adapter._patch is None


def test_crewai_unregister_is_noop_when_never_registered() -> None:
    adapter = CrewAIAdapter()
    # No exception when no patch is installed.
    adapter.unregister_hooks()
    assert adapter._patch is None


def test_langchain_adapter_metadata_and_process_agent_id() -> None:
    adapter = LangChainAdapter(process_agent_id="proc-1")
    assert adapter.get_framework_name() == "langchain"
    assert adapter.get_supported_versions() == [">=0.1.0"]
    assert adapter.process_agent_id == "proc-1"

    adapter.process_agent_id = "proc-2"
    assert adapter.process_agent_id == "proc-2"


def test_langchain_adapter_register_unregister_and_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent_assembly.adapters.langchain.adapter.LangChainPatch", _FakePatch)
    monkeypatch.setattr(
        "agent_assembly.adapters.langchain.adapter.get_active_callback_handler",
        lambda: "the-handler",
    )
    adapter = LangChainAdapter()

    adapter.register_hooks(MagicMock())
    assert isinstance(adapter._patch, _FakePatch)
    assert adapter.get_callback_handler() == "the-handler"

    adapter.unregister_hooks()
    assert adapter._patch is None
    adapter.unregister_hooks()  # idempotent


def test_langgraph_adapter_metadata_and_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent_assembly.adapters.langgraph.adapter.LangGraphPatch", _FakePatch)
    adapter = LangGraphAdapter()
    assert adapter.get_framework_name() == "langgraph"
    assert adapter.get_supported_versions() == [">=0.1.0"]
    assert adapter.process_agent_id is None

    adapter.process_agent_id = "lg-1"
    adapter.register_hooks(MagicMock())
    assert isinstance(adapter._patch, _FakePatch)

    adapter.unregister_hooks()
    assert adapter._patch is None


def test_openai_agents_adapter_metadata_and_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent_assembly.adapters.openai_agents.adapter.OpenAIAgentsPatch", _FakePatch)
    adapter = OpenAIAgentsAdapter(process_agent_id="oa-1")
    assert adapter.get_framework_name() == "openai"
    assert adapter.get_supported_versions() == [">=1.0.0"]
    assert adapter.process_agent_id == "oa-1"
    adapter.process_agent_id = "oa-2"
    assert adapter.process_agent_id == "oa-2"

    adapter.register_hooks(MagicMock())
    assert isinstance(adapter._patch, _FakePatch)
    adapter.unregister_hooks()
    assert adapter._patch is None


def test_openai_agents_is_available_false_when_module_absent() -> None:
    # openai.agents is not installed in the test env.
    assert OpenAIAgentsAdapter().is_available() is False


def test_openai_agents_is_available_false_when_find_spec_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(_name: str) -> Any:
        raise ValueError("namespace package without __spec__")

    monkeypatch.setattr(
        "agent_assembly.adapters.openai_agents.adapter.importlib.util.find_spec",
        boom,
    )
    assert OpenAIAgentsAdapter().is_available() is False


def test_google_adk_adapter_metadata_and_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent_assembly.adapters.google_adk.adapter.GoogleADKPatch", _FakePatch)
    adapter = GoogleADKAdapter()
    assert adapter.get_framework_name() == "google_adk"
    assert adapter.get_supported_versions() == [">=1.0.0,<2.0"]
    assert adapter.process_agent_id is None
    adapter.process_agent_id = "g-1"
    assert adapter.process_agent_id == "g-1"

    adapter.register_hooks(MagicMock())
    assert isinstance(adapter._patch, _FakePatch)
    adapter.unregister_hooks()
    assert adapter._patch is None


def test_google_adk_is_available_false_when_module_absent() -> None:
    # google.adk is not installed; find_spec on the missing parent namespace
    # must be caught and reported as unavailable.
    assert GoogleADKAdapter().is_available() is False


def test_google_adk_is_available_false_when_find_spec_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(_name: str) -> Any:
        raise ModuleNotFoundError("google parent namespace absent")

    monkeypatch.setattr(
        "agent_assembly.adapters.google_adk.adapter.importlib.util.find_spec",
        boom,
    )
    assert GoogleADKAdapter().is_available() is False


def test_mcp_adapter_metadata_and_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent_assembly.adapters.mcp.adapter.MCPClientPatch", _FakePatch)
    adapter = MCPAdapter(process_agent_id="mcp-1")
    assert adapter.get_framework_name() == "mcp"
    assert adapter.get_supported_versions() == [">=1.0.0"]
    assert adapter.process_agent_id == "mcp-1"
    adapter.process_agent_id = "mcp-2"
    assert adapter.process_agent_id == "mcp-2"

    adapter.register_hooks(MagicMock())
    assert isinstance(adapter._patch, _FakePatch)
    adapter.unregister_hooks()
    assert adapter._patch is None


def test_pydantic_ai_adapter_metadata_and_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent_assembly.adapters.pydantic_ai.adapter.PydanticAIPatch", _FakePatch)
    adapter = PydanticAIAdapter()
    assert adapter.get_framework_name() == "pydantic_ai"
    assert adapter.get_supported_versions() == [">=0.1.0"]
    assert adapter.process_agent_id is None
    adapter.process_agent_id = "pa-1"
    assert adapter.process_agent_id == "pa-1"

    adapter.register_hooks(MagicMock())
    assert isinstance(adapter._patch, _FakePatch)
    adapter.unregister_hooks()
    assert adapter._patch is None
