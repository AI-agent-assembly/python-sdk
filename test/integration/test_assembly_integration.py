"""
Integration test stub for the Agent Assembly SDK.

This file contains integration tests for the SDK.
These tests require a running gateway instance.
"""

import pytest

from agent_assembly import init_assembly
from agent_assembly.exceptions import ConfigurationError


@pytest.mark.integration
def test_init_assembly_with_valid_config():
    """Test that assembly initialization works with valid configuration."""
    # This test requires a running gateway
    assembly = init_assembly(
        gateway_url="http://localhost:8080",
        agent_id="test-agent-001",
    )
    assert assembly is not None
    assert assembly.agent_id == "test-agent-001"
    assembly.close()


@pytest.mark.integration
def test_init_assembly_with_invalid_config():
    """Test that assembly initialization fails with invalid configuration."""
    with pytest.raises(ConfigurationError):
        init_assembly(
            gateway_url="",  # Invalid: empty URL
            agent_id="test-agent-001",
        )

    with pytest.raises(ConfigurationError):
        init_assembly(
            gateway_url="http://localhost:8080",
            agent_id="",  # Invalid: empty agent ID
        )


@pytest.mark.integration
async def test_gateway_client_context_manager():
    """Test that the gateway client works as a context manager."""
    assembly = init_assembly(
        gateway_url="http://localhost:8080",
        agent_id="test-agent-001",
    )
    
    with assembly:
        assert assembly.client is not None
    
    # Client should be closed after exiting context
    assert assembly._client is None
