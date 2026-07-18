from __future__ import annotations

import pytest

from agent_assembly import init_assembly
from agent_assembly.adapters.langchain.runtime import (
    _reset_runtime_state_for_tests,
    auto_inject_callback_handler,
    get_active_callback_handler,
)
from agent_assembly.core import assembly as core_assembly
from agent_assembly.exceptions import ConfigurationError


def _reset_assembly_state() -> None:
    active_context = core_assembly._ACTIVE_CONTEXT
    if active_context is not None and not active_context.is_shutdown:
        active_context.shutdown()
    core_assembly._ACTIVE_CONTEXT = None


def test_auto_inject_callback_handler_is_idempotent() -> None:
    _reset_runtime_state_for_tests()
    _reset_assembly_state()

    interceptor = object()
    first = auto_inject_callback_handler(interceptor=interceptor)
    second = auto_inject_callback_handler(interceptor=interceptor)

    assert first is second
    assert get_active_callback_handler() is first


def test_reinject_different_interceptor_warns_and_replaces() -> None:
    _reset_runtime_state_for_tests()
    _reset_assembly_state()

    first = auto_inject_callback_handler(interceptor=object())

    with pytest.warns(RuntimeWarning):
        second = auto_inject_callback_handler(interceptor=object())

    # The stale handler must not be silently kept when the config differs.
    assert second is not first
    assert get_active_callback_handler() is second


def test_init_assembly_auto_injects_callback_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_runtime_state_for_tests()
    _reset_assembly_state()

    def fake_register_adapters(**kwargs: object) -> list[object]:
        auto_inject_callback_handler(kwargs["client"])
        return []

    monkeypatch.setattr(core_assembly, "_register_adapters", fake_register_adapters)
    monkeypatch.setattr(
        core_assembly,
        "_start_network_layer",
        lambda **kwargs: ("sdk-only", core_assembly._noop_shutdown),
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


def test_init_assembly_reuses_existing_callback_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_runtime_state_for_tests()
    _reset_assembly_state()

    def fake_register_adapters(**kwargs: object) -> list[object]:
        auto_inject_callback_handler(kwargs["client"])
        return []

    monkeypatch.setattr(core_assembly, "_register_adapters", fake_register_adapters)
    monkeypatch.setattr(
        core_assembly,
        "_start_network_layer",
        lambda **kwargs: ("sdk-only", core_assembly._noop_shutdown),
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
