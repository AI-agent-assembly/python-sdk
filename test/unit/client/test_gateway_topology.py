"""Unit tests for GatewayClient topology param storage (AAASM-958).

The REST ``register_agent`` wire-shape tests were retired in AAASM-3402 when
registration moved to the native gRPC path; only the constructor-storage
contract of the topology fields is exercised here.
"""

from __future__ import annotations

from agent_assembly.client.gateway import GatewayClient


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
