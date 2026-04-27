from __future__ import annotations

from agent_assembly import init_assembly
from agent_assembly.adapters.langchain.runtime import (
    _reset_runtime_state_for_tests,
    auto_inject_callback_handler,
    get_active_callback_handler,
)


def test_auto_inject_callback_handler_is_idempotent() -> None:
    _reset_runtime_state_for_tests()

    first = auto_inject_callback_handler(interceptor=object())
    second = auto_inject_callback_handler(interceptor=object())

    assert first is second
    assert get_active_callback_handler() is first


def test_init_assembly_auto_injects_callback_handler() -> None:
    _reset_runtime_state_for_tests()

    client = init_assembly(gateway_url="http://localhost:8080", agent_id="test-agent")
    try:
        assert get_active_callback_handler() is not None
    finally:
        client.close()


def test_init_assembly_reuses_existing_callback_handler() -> None:
    _reset_runtime_state_for_tests()

    first_client = init_assembly(gateway_url="http://localhost:8080", agent_id="test-agent-a")
    second_client = init_assembly(gateway_url="http://localhost:8080", agent_id="test-agent-b")
    try:
        first_handler = get_active_callback_handler()
        assert first_handler is not None
        assert get_active_callback_handler() is first_handler
    finally:
        first_client.close()
        second_client.close()
