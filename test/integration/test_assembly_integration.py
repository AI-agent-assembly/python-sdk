"""
Integration test stub for the Agent Assembly SDK.

This file contains integration tests for the SDK.
These tests require a running gateway instance.
"""

import pytest

from agent_assembly import init_assembly
from agent_assembly.core import assembly as core_assembly
from agent_assembly.exceptions import ConfigurationError


@pytest.fixture(autouse=True)
def _force_pure_python_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep init_assembly() hermetic whether or not the native ``_core`` extension
    is built (AAASM-4906, sibling of AAASM-4898).

    With a native ``.so`` present, ``_native_core_available()`` returns True and
    init dials a real gateway over gRPC (``connect_runtime_client`` /
    ``register_agent``). These tests exercise SDK wiring without a live gateway,
    so forcing the pure-Python path (the CI default) keeps them deterministic in
    both build modes.
    """
    monkeypatch.setattr(core_assembly, "_native_core_available", lambda: False)


@pytest.mark.integration
def test_init_assembly_with_valid_config() -> None:
    """Test that assembly initialization works with valid configuration."""
    # This test requires a running gateway
    context = init_assembly(
        gateway_url="http://localhost:8080",
        api_key="test-api-key",
        agent_id="test-agent-001",
    )
    assert context is not None
    assert context.client.agent_id == "test-agent-001"
    context.shutdown()


@pytest.mark.integration
def test_init_assembly_with_invalid_config() -> None:
    """Test that assembly initialization fails with an unknown runtime mode."""
    with pytest.raises(ConfigurationError):
        init_assembly(
            gateway_url="http://localhost:8080",
            api_key="test-api-key",
            mode="invalid-mode",  # type: ignore[arg-type]
        )


@pytest.mark.integration
def test_gateway_client_context_manager() -> None:
    """Test that the gateway client works as a context manager."""
    context = init_assembly(
        gateway_url="http://localhost:8080",
        api_key="test-api-key",
        agent_id="test-agent-001",
    )

    with context:
        assert context.client.client is not None

    # Client should be closed after exiting context
    assert context.client._client is None
