"""Core assembly initialization module."""

from __future__ import annotations

from typing import Optional

from agent_assembly.adapters.langchain.runtime import auto_inject_callback_handler
from agent_assembly.client.gateway import GatewayClient
from agent_assembly.exceptions import ConfigurationError


def init_assembly(
    gateway_url: str,
    agent_id: str,
    api_key: Optional[str] = None,
) -> GatewayClient:
    """
    Initialize the Agent Assembly SDK.

    Args:
        gateway_url: URL of the governance gateway
        agent_id: Unique identifier for the agent
        api_key: Optional API key for authentication

    Returns:
        Configured GatewayClient instance

    Raises:
        ConfigurationError: If initialization fails
    """
    if not gateway_url:
        raise ConfigurationError("gateway_url is required")
    if not agent_id:
        raise ConfigurationError("agent_id is required")

    client = GatewayClient(
        gateway_url=gateway_url,
        agent_id=agent_id,
        api_key=api_key,
    )
    auto_inject_callback_handler(interceptor=object())
    return client
