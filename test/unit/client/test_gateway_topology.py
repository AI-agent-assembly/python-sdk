"""Unit tests for GatewayClient topology param forwarding (AAASM-958)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_assembly.client.gateway import GatewayClient


def _make_ok_response() -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {"registration_id": "reg-1"}
    resp.raise_for_status = MagicMock()
    return resp


def test_gateway_client_stores_topology_fields() -> None:
    client = GatewayClient(
        gateway_url="http://gw.test",
        agent_id="a",
        api_key="k",
        parent_agent_id="p",
        team_id="t",
        delegation_reason="r",
        spawned_by_tool="search_tool",
    )
    assert client.parent_agent_id == "p"
    assert client.team_id == "t"
    assert client.delegation_reason == "r"
    assert client.spawned_by_tool == "search_tool"


def test_gateway_client_topology_defaults_to_none() -> None:
    client = GatewayClient(gateway_url="http://gw.test", agent_id="a", api_key="k")
    assert client.parent_agent_id is None
    assert client.team_id is None
    assert client.delegation_reason is None
    assert client.spawned_by_tool is None


@pytest.mark.asyncio
async def test_register_agent_sends_topology_fields() -> None:
    client = GatewayClient(
        gateway_url="http://gw.test",
        agent_id="agent-child",
        api_key="key",
        parent_agent_id="agent-parent",
        team_id="team-alpha",
        delegation_reason="sub-task delegation",
        spawned_by_tool="search_tool",
    )
    mock_post = MagicMock(return_value=_make_ok_response())
    with patch.object(
        type(client),
        "client",
        new_callable=lambda: property(lambda self: MagicMock(post=mock_post)),
    ):
        await client.register_agent()

    _, kwargs = mock_post.call_args
    body = kwargs.get("json") or {}
    assert body["parent_agent_id"] == "agent-parent"
    assert body["team_id"] == "team-alpha"
    assert body["delegation_reason"] == "sub-task delegation"
    assert body["spawned_by_tool"] == "search_tool"


@pytest.mark.asyncio
async def test_register_agent_omits_body_when_no_topology() -> None:
    client = GatewayClient(
        gateway_url="http://gw.test",
        agent_id="agent-1",
        api_key="key",
    )
    mock_post = MagicMock(return_value=_make_ok_response())
    with patch.object(
        type(client),
        "client",
        new_callable=lambda: property(lambda self: MagicMock(post=mock_post)),
    ):
        await client.register_agent()

    _, kwargs = mock_post.call_args
    assert kwargs.get("json") is None
