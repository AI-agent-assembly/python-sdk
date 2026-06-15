"""Gateway client for communication with the governance gateway."""

from __future__ import annotations

from typing import Any

import httpx

from agent_assembly.client.dispatch import DispatchToolResult
from agent_assembly.exceptions import GatewayError


class GatewayClient:
    """Client for communicating with the Agent Assembly governance gateway."""

    def __init__(
        self,
        gateway_url: str,
        agent_id: str,
        api_key: str | None = None,
        timeout: int = 30,
        *,
        control_plane_url: str | None = None,
        parent_agent_id: str | None = None,
        team_id: str | None = None,
        delegation_reason: str | None = None,
        spawned_by_tool: str | None = None,
        depth: int | None = None,
        enforcement_mode: str | None = None,
    ) -> None:
        """
        Initialize the GatewayClient.

        Args:
            gateway_url: URL of the governance gateway
            agent_id: Unique identifier for the agent
            api_key: Optional API key for authentication
            timeout: Request timeout in seconds
            control_plane_url: Optional URL of the control-plane HTTP API. When
                set, the HTTP routes (``/agents/{id}/register``, ``/policy/check``,
                ``/topology/edges``) are issued against it; when ``None`` (the
                default) they fall back to ``gateway_url`` — the backwards-compatible
                single-host OSS dev setup.
            parent_agent_id: Parent agent ID for topology tracking
            team_id: Team ID this agent belongs to
            delegation_reason: Human-readable reason for delegation
            spawned_by_tool: Name of the tool that spawned this agent
            depth: Spawn depth in the agent lineage tree
            enforcement_mode: Per-agent governance posture sent to the gateway
                at registration. ``None`` (the default) omits the field from
                the request body so a legacy gateway sees the same wire shape
                as before; the gateway then defaults to live enforcement.
        """
        self.gateway_url = gateway_url.rstrip("/")
        self.control_plane_url = control_plane_url.rstrip("/") if control_plane_url else None
        self.agent_id = agent_id
        self.api_key = api_key
        self.timeout = timeout
        self.parent_agent_id = parent_agent_id
        self.team_id = team_id
        self.delegation_reason = delegation_reason
        self.spawned_by_tool = spawned_by_tool
        self.depth = depth
        self.enforcement_mode = enforcement_mode
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        """Get or create the HTTP client.

        The base URL is ``control_plane_url`` when one was supplied, otherwise
        it falls back to ``gateway_url`` (single-host OSS dev).
        """
        if self._client is None:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.Client(
                base_url=self.control_plane_url or self.gateway_url,
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

    async def register_agent(self) -> dict[str, Any]:
        """
        Register the agent with the governance gateway.

        Returns:
            Registration response data

        Raises:
            GatewayError: If registration fails
        """
        body: dict[str, str | int] = {}
        if self.parent_agent_id is not None:
            body["parent_agent_id"] = self.parent_agent_id
        if self.team_id is not None:
            body["team_id"] = self.team_id
        if self.delegation_reason is not None:
            body["delegation_reason"] = self.delegation_reason
        if self.spawned_by_tool is not None:
            body["spawned_by_tool"] = self.spawned_by_tool
        if self.depth is not None:
            body["depth"] = self.depth
        if self.enforcement_mode is not None:
            body["enforcement_mode"] = self.enforcement_mode
        try:
            response = self.client.post(
                f"/agents/{self.agent_id}/register",
                json=body if body else None,
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return data
        except httpx.HTTPError as e:
            raise GatewayError(f"Failed to register agent: {e}") from e

    async def check_policy_compliance(self, action: str) -> dict[str, Any]:
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
            data: dict[str, Any] = response.json()
            return data
        except httpx.HTTPError as e:
            raise GatewayError(f"Failed to check policy compliance: {e}") from e

    def report_edge(
        self,
        source_agent_id: str,
        target_agent_id: str,
        edge_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Report a directed edge between two agents to the topology store.

        Args:
            source_agent_id: ID of the source agent
            target_agent_id: ID of the target agent
            edge_type: Semantic type of the edge (e.g. "messages", "delegates_to")
            metadata: Optional freeform metadata to attach to the edge

        Returns:
            Response data containing the assigned edge id

        Raises:
            GatewayError: If the request fails
        """
        import json as _json

        body: dict[str, str] = {
            "source_agent_id": source_agent_id,
            "target_agent_id": target_agent_id,
            "edge_type": edge_type,
        }
        if metadata is not None:
            body["metadata_json"] = _json.dumps(metadata)
        try:
            response = self.client.post("/topology/edges", json=body)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return data
        except httpx.HTTPError as e:
            raise GatewayError(f"Failed to report edge: {e}") from e

    async def dispatch_tool(self, tool_name: str, args: dict[str, Any]) -> DispatchToolResult:
        """
        Dispatch a tool with placeholder-form args (AAASM-1920 Secret Injection).

        The gateway resolves every ``${NAME}`` placeholder in ``args`` against
        its registered ``SecretsStore``, emits a placeholder-form audit entry,
        and returns the resolved args plus the list of substituted names.

        The LLM never observes the resolved credential value: the agent code
        holds the placeholder, Assembly resolves it on the gateway side, and
        the response is forwarded to the tool sink only.

        Args:
            tool_name: Name of the tool to dispatch (e.g. ``"call_database"``).
            args: Placeholder-form args. May contain ``${NAME}`` tokens that
                will be resolved server-side before the tool is invoked.

        Returns:
            ``DispatchToolResult`` with the resolved args + the list of
            placeholder names that were substituted.

        Raises:
            GatewayError: If the request fails for any reason — including a
                422 Unprocessable Entity when ``args`` references a placeholder
                that is not registered in the gateway's ``SecretsStore``.
        """
        body = {"tool": tool_name, "args": args}
        try:
            response = self.client.post("/dispatch_tool", json=body)
            response.raise_for_status()
            data = response.json()
            return DispatchToolResult(
                resolved_args=data.get("resolved_args", {}),
                names_substituted=list(data.get("names_substituted", [])),
            )
        except httpx.HTTPError as e:
            raise GatewayError(f"Failed to dispatch tool {tool_name}: {e}") from e
