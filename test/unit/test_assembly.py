"""
Unit tests for the Agent Assembly SDK.

These tests verify the basic SDK functionality without requiring external dependencies.
"""

import pytest

from agent_assembly import init_assembly
from agent_assembly.exceptions import ConfigurationError


def test_init_assembly_with_valid_config():
    """Test that assembly initialization works with valid configuration."""
    assembly = init_assembly(
        gateway_url="http://localhost:8080",
        agent_id="test-agent-001",
    )
    assert assembly is not None
    assert assembly.agent_id == "test-agent-001"
    assert assembly.gateway_url == "http://localhost:8080"
    assembly.close()


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


def test_gateway_client_context_manager():
    """Test that the gateway client works as a context manager."""
    assembly = init_assembly(
        gateway_url="http://localhost:8080",
        agent_id="test-agent-001",
    )
    
    with assembly:
        assert assembly.client is not None
    
    # Client should be closed after exiting context
    assert assembly._client is None


def test_gateway_client_with_api_key():
    """Test that the gateway client can be initialized with an API key."""
    assembly = init_assembly(
        gateway_url="http://localhost:8080",
        agent_id="test-agent-001",
        api_key="test-api-key",
    )
    assert assembly.api_key == "test-api-key"
    assembly.close()
