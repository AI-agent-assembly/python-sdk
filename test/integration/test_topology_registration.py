"""Integration tests for topology field forwarding in the register_agent call (AAASM-1178).

Uses httpx.MockTransport to intercept HTTP traffic so tests run without a live gateway.
"""

from __future__ import annotations

import httpx
import pytest

from agent_assembly import init_assembly
from agent_assembly.client.gateway import GatewayClient


def _make_transport(captured: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"registration_id": "reg-test-001"})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_register_agent_topology_fields_reach_gateway() -> None:
    """init_assembly + register_agent sends all 4 topology fields to the gateway."""
    captured: list[httpx.Request] = []
    transport = _make_transport(captured)

    context = init_assembly(
        gateway_url="http://gateway.test",
        api_key="test-api-key",
        agent_id="agent-child-001",
        mode="sdk-only",
        parent_agent_id="agent-parent-001",
        team_id="team-alpha",
        delegation_reason="sub-task delegation",
        spawned_by_tool="search_tool",
    )

    context.client._client = httpx.Client(
        base_url="http://gateway.test",
        transport=transport,
    )

    await context.client.register_agent()
    context.shutdown()

    assert len(captured) == 1, f"expected 1 request, got {len(captured)}"
    body = captured[0].read()
    import json

    payload = json.loads(body)

    assert payload["parent_agent_id"] == "agent-parent-001"
    assert payload["team_id"] == "team-alpha"
    assert payload["delegation_reason"] == "sub-task delegation"
    assert payload["spawned_by_tool"] == "search_tool"


@pytest.mark.asyncio
async def test_register_agent_no_topology_omits_body() -> None:
    """When no topology params are provided, register_agent sends an empty/null body."""
    captured: list[httpx.Request] = []
    transport = _make_transport(captured)

    context = init_assembly(
        gateway_url="http://gateway.test",
        api_key="test-api-key",
        agent_id="agent-001",
        mode="sdk-only",
    )

    context.client._client = httpx.Client(
        base_url="http://gateway.test",
        transport=transport,
    )

    await context.client.register_agent()
    context.shutdown()

    assert len(captured) == 1
    body = captured[0].read()
    # No topology fields → httpx sends null body (no Content-Type: application/json)
    assert body == b"" or body == b"null", f"expected empty body when no topology, got {body!r}"


@pytest.mark.asyncio
async def test_register_agent_partial_topology_only_sends_set_fields() -> None:
    """When only some topology fields are set, only those are included in the body."""
    captured: list[httpx.Request] = []
    transport = _make_transport(captured)

    context = init_assembly(
        gateway_url="http://gateway.test",
        api_key="test-api-key",
        agent_id="agent-partial-001",
        mode="sdk-only",
        team_id="team-beta",
    )

    context.client._client = httpx.Client(
        base_url="http://gateway.test",
        transport=transport,
    )

    await context.client.register_agent()
    context.shutdown()

    import json

    assert len(captured) == 1
    payload = json.loads(captured[0].read())

    assert payload.get("team_id") == "team-beta"
    assert "parent_agent_id" not in payload
    assert "delegation_reason" not in payload
    assert "spawned_by_tool" not in payload


def test_gateway_client_stores_topology_fields_at_construction() -> None:
    """GatewayClient stores all 4 topology fields on construction (integration smoke)."""
    client = GatewayClient(
        gateway_url="http://gw.test",
        agent_id="agent-001",
        api_key="key-001",
        parent_agent_id="parent-999",
        team_id="team-gamma",
        delegation_reason="handoff from orchestrator",
        spawned_by_tool="file_reader",
    )

    assert client.parent_agent_id == "parent-999"
    assert client.team_id == "team-gamma"
    assert client.delegation_reason == "handoff from orchestrator"
    assert client.spawned_by_tool == "file_reader"
