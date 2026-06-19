"""Integration smoke test for GatewayClient topology field storage (AAASM-1178).

The REST ``register_agent`` topology-forwarding tests were retired in
AAASM-3402 when registration moved to the native gRPC ``register`` path. The
native register call does not yet carry the lineage fields, so forwarding them
over the native path is a tracked follow-up; until then this only asserts the
fields are stored at construction.
"""

from __future__ import annotations

from agent_assembly.client.gateway import GatewayClient


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
