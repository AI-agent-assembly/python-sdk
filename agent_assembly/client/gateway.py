"""Gateway client for communication with the governance gateway."""

from __future__ import annotations

from typing import Optional

import httpx

from agent_assembly.exceptions import GatewayError


class GatewayClient:
    """Client for communicating with the Agent Assembly governance gateway."""

    def __init__(
        self,
        gateway_url: str,
        agent_id: str,
        api_key: Optional[str] = None,
        timeout: int = 30,
        *,
        parent_agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        delegation_reason: Optional[str] = None,
    ) -> None:
        """
        Initialize the GatewayClient.

        Args:
            gateway_url: URL of the governance gateway
            agent_id: Unique identifier for the agent
            api_key: Optional API key for authentication
            timeout: Request timeout in seconds
            parent_agent_id: Parent agent ID for topology tracking
            team_id: Team ID this agent belongs to
            delegation_reason: Human-readable reason for delegation
        """
        self.gateway_url = gateway_url.rstrip("/")
        self.agent_id = agent_id
        self.api_key = api_key
        self.timeout = timeout
        self.parent_agent_id = parent_agent_id
        self.team_id = team_id
        self.delegation_reason = delegation_reason
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        """Get or create the HTTP client."""
        if self._client is None:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.Client(
                base_url=self.gateway_url,
                headers=headers,
                timeout=self.timeout,
            )
        return self._client

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> GatewayClient:
        """Context manager entry."""
        return self

    def __exit__(self, *args: object) -> None:
        """Context manager exit."""
        self.close()

    async def register_agent(self) -> dict:
        """
        Register the agent with the governance gateway.

        Returns:
            Registration response data

        Raises:
            GatewayError: If registration fails
        """
        body: dict[str, str] = {}
        if self.parent_agent_id is not None:
            body["parent_agent_id"] = self.parent_agent_id
        if self.team_id is not None:
            body["team_id"] = self.team_id
        if self.delegation_reason is not None:
            body["delegation_reason"] = self.delegation_reason
        try:
            response = self.client.post(
                f"/agents/{self.agent_id}/register",
                json=body if body else None,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise GatewayError(f"Failed to register agent: {e}") from e

    async def check_policy_compliance(self, action: str) -> dict:
        """
        Check if an action complies with governance policies.

        Args:
            action: The action to check

        Returns:
            Policy compliance response

        Raises:
            GatewayError: If policy check fails
        """
        try:
            response = self.client.post(
                f"/agents/{self.agent_id}/policy/check",
                json={"action": action},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise GatewayError(f"Failed to check policy compliance: {e}") from e
