"""Unit tests for GatewayClient control_plane_url routing (AAASM-2028)."""

from __future__ import annotations

from agent_assembly.client.gateway import GatewayClient


def test_control_plane_url_defaults_to_none() -> None:
    """Omitting control_plane_url leaves it unset (backwards-compatible)."""
    client = GatewayClient(gateway_url="http://gw.test", agent_id="a")
    assert client.control_plane_url is None


def test_control_plane_url_is_stored_and_trimmed() -> None:
    """A supplied control_plane_url is stored with a trailing slash stripped."""
    client = GatewayClient(
        gateway_url="http://gw.test",
        agent_id="a",
        control_plane_url="http://cp.test/",
    )
    assert client.control_plane_url == "http://cp.test"


def test_http_client_base_url_falls_back_to_gateway_url() -> None:
    """Without control_plane_url the httpx base URL is the gateway URL."""
    with GatewayClient(gateway_url="http://gw.test", agent_id="a") as client:
        assert str(client.client.base_url) == "http://gw.test"


def test_http_client_base_url_uses_control_plane_url_when_set() -> None:
    """When control_plane_url is set, HTTP routes target it, not gateway_url."""
    with GatewayClient(
        gateway_url="http://gw.test",
        agent_id="a",
        control_plane_url="http://cp.test",
    ) as client:
        assert str(client.client.base_url) == "http://cp.test"
