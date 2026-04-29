from __future__ import annotations

import pytest

from agent_assembly import init_assembly
from agent_assembly.core import assembly as core_assembly
from agent_assembly.adapters.langchain.runtime import (
    _reset_runtime_state_for_tests,
    auto_inject_callback_handler,
    get_active_callback_handler,
)
from agent_assembly.exceptions import ConfigurationError


def _reset_assembly_state() -> None:
    active_context = core_assembly._ACTIVE_CONTEXT
    if active_context is not None and not active_context.is_shutdown:
        active_context.shutdown()
    core_assembly._ACTIVE_CONTEXT = None


def test_auto_inject_callback_handler_is_idempotent() -> None:
    _reset_runtime_state_for_tests()
    _reset_assembly_state()

    first = auto_inject_callback_handler(interceptor=object())
    second = auto_inject_callback_handler(interceptor=object())

    assert first is second
    assert get_active_callback_handler() is first


def test_init_assembly_auto_injects_callback_handler(monkeypatch) -> None:
    _reset_runtime_state_for_tests()
    _reset_assembly_state()
    monkeypatch.setattr(
        core_assembly,
        "_is_installed",
        lambda package: package == "langchain",
    )

    context = init_assembly(
        gateway_url="http://localhost:8080",
        api_key="test-api-key",
        agent_id="test-agent",
    )
    try:
        assert get_active_callback_handler() is not None
    finally:
        context.shutdown()


def test_init_assembly_reuses_existing_callback_handler(monkeypatch) -> None:
    _reset_runtime_state_for_tests()
    _reset_assembly_state()
    monkeypatch.setattr(
        core_assembly,
        "_is_installed",
        lambda package: package == "langchain",
    )

    first_context = init_assembly(
        gateway_url="http://localhost:8080",
        api_key="test-api-key",
        agent_id="test-agent-a",
    )
    second_context = init_assembly(
        gateway_url="http://localhost:8080",
        api_key="test-api-key",
        agent_id="test-agent-a",
    )
    try:
        first_handler = get_active_callback_handler()
        assert first_handler is not None
        assert get_active_callback_handler() is first_handler
        assert first_context is second_context
        with pytest.raises(ConfigurationError):
            init_assembly(
                gateway_url="http://localhost:8080",
                api_key="test-api-key",
                agent_id="test-agent-b",
            )
    finally:
        first_context.shutdown()
        second_context.shutdown()
