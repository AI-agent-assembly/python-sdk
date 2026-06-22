"""Unit tests for the Microsoft Agent Framework adapter contract."""

from __future__ import annotations

from typing import Any

import pytest

from agent_assembly.adapters.microsoft_agent_framework.adapter import (
    MicrosoftAgentFrameworkAdapter,
)


def test_framework_name_and_versions() -> None:
    adapter = MicrosoftAgentFrameworkAdapter()
    assert adapter.get_framework_name() == "microsoft_agent_framework"
    versions = adapter.get_supported_versions()
    assert versions == [">=1.0.0,<2.0"]
    # Contract validation must pass for a registerable adapter.
    adapter.validate_registration()


def test_is_available_detects_agent_framework_not_framework_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """``is_available`` must probe ``agent_framework`` — not the framework name.

    The framework name (``microsoft_agent_framework``) is intentionally not the
    importable module (``agent_framework``). Probing the name would always miss
    and silently disable governance (AAASM-3528).
    """
    adapter = MicrosoftAgentFrameworkAdapter()

    probed: list[str] = []

    def fake_find_spec(name: str) -> Any:
        probed.append(name)
        return object() if name == "agent_framework" else None

    monkeypatch.setattr(
        "agent_assembly.adapters.microsoft_agent_framework.adapter.importlib.util.find_spec",
        fake_find_spec,
    )
    assert adapter.is_available() is True
    assert probed == ["agent_framework"]


def test_is_available_false_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = MicrosoftAgentFrameworkAdapter()

    monkeypatch.setattr(
        "agent_assembly.adapters.microsoft_agent_framework.adapter.importlib.util.find_spec",
        lambda _name: None,
    )
    assert adapter.is_available() is False


def test_is_available_handles_module_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = MicrosoftAgentFrameworkAdapter()

    def raise_mnfe(_name: str) -> Any:
        raise ModuleNotFoundError("agent_framework")

    monkeypatch.setattr(
        "agent_assembly.adapters.microsoft_agent_framework.adapter.importlib.util.find_spec",
        raise_mnfe,
    )
    assert adapter.is_available() is False


def test_process_agent_id_round_trips() -> None:
    adapter = MicrosoftAgentFrameworkAdapter(process_agent_id="agent-7")
    assert adapter.process_agent_id == "agent-7"
    adapter.set_process_agent_id("agent-9")
    assert adapter.process_agent_id == "agent-9"


def test_registered_as_builtin_adapter() -> None:
    from agent_assembly.adapters.registry import AdapterRegistry

    registry = AdapterRegistry()
    assert "microsoft_agent_framework" in registry._registered
    assert registry._registered["microsoft_agent_framework"].get_framework_name() == "microsoft_agent_framework"
