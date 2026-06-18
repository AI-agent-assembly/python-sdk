"""Unit tests for the remaining `GatewayClient` HTTP endpoints.

Covers `check_policy_compliance`, `report_edge`, the API-key auth header, and
the `register_agent` failure branch — the success/error paths not already
exercised by the topology and dispatch_tool suites.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agent_assembly.client.gateway import GatewayClient
from agent_assembly.exceptions import GatewayError


def _ok(json_body: dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = json_body
    resp.raise_for_status = MagicMock()
    return resp


def _raising(exc: Exception) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock(side_effect=exc)
    return resp


def _patch_post(client: GatewayClient, mock_post: MagicMock) -> Any:
    return patch.object(
        type(client),
        "client",
        new_callable=lambda: property(lambda self: MagicMock(post=mock_post)),
    )


def test_http_client_sets_bearer_auth_header_when_api_key_present() -> None:
    client = GatewayClient(gateway_url="http://gw.test", agent_id="a", api_key="sekret")
    try:
        assert client.client.headers["Authorization"] == "Bearer sekret"
    finally:
        client.close()


def test_http_client_omits_auth_header_when_no_api_key() -> None:
    client = GatewayClient(gateway_url="http://gw.test", agent_id="a")
    try:
        assert "Authorization" not in client.client.headers
    finally:
        client.close()


@pytest.mark.asyncio
async def test_register_agent_raises_gateway_error_on_http_error() -> None:
    client = GatewayClient(gateway_url="http://gw.test", agent_id="a", api_key="k")
    mock_post = MagicMock(return_value=_raising(httpx.ConnectError("refused")))
    with _patch_post(client, mock_post):
        with pytest.raises(GatewayError, match="Failed to register agent"):
            await client.register_agent()


@pytest.mark.asyncio
async def test_check_policy_compliance_returns_decision_on_success() -> None:
    client = GatewayClient(gateway_url="http://gw.test", agent_id="a", api_key="k")
    mock_post = MagicMock(return_value=_ok({"allowed": True, "reason": "ok"}))
    with _patch_post(client, mock_post):
        result = await client.check_policy_compliance("send_email")

    assert result == {"allowed": True, "reason": "ok"}
    _, kwargs = mock_post.call_args
    assert kwargs["json"] == {"action": "send_email"}


@pytest.mark.asyncio
async def test_check_policy_compliance_raises_gateway_error_on_http_error() -> None:
    client = GatewayClient(gateway_url="http://gw.test", agent_id="a", api_key="k")
    mock_post = MagicMock(return_value=_raising(httpx.ReadTimeout("slow")))
    with _patch_post(client, mock_post):
        with pytest.raises(GatewayError, match="Failed to check policy compliance"):
            await client.check_policy_compliance("send_email")


def test_report_edge_serializes_metadata_and_returns_edge_id() -> None:
    client = GatewayClient(gateway_url="http://gw.test", agent_id="a", api_key="k")
    mock_post = MagicMock(return_value=_ok({"edge_id": "e-9"}))
    with _patch_post(client, mock_post):
        result = client.report_edge("src", "dst", "delegates_to", {"weight": 2})

    assert result == {"edge_id": "e-9"}
    _, kwargs = mock_post.call_args
    body = kwargs["json"]
    assert body["source_agent_id"] == "src"
    assert body["target_agent_id"] == "dst"
    assert body["edge_type"] == "delegates_to"
    # metadata is JSON-encoded into metadata_json.
    assert body["metadata_json"] == '{"weight": 2}'


def test_report_edge_omits_metadata_json_when_metadata_none() -> None:
    client = GatewayClient(gateway_url="http://gw.test", agent_id="a", api_key="k")
    mock_post = MagicMock(return_value=_ok({"edge_id": "e-1"}))
    with _patch_post(client, mock_post):
        client.report_edge("src", "dst", "messages")

    _, kwargs = mock_post.call_args
    assert "metadata_json" not in kwargs["json"]


def test_report_edge_raises_gateway_error_on_http_error() -> None:
    client = GatewayClient(gateway_url="http://gw.test", agent_id="a", api_key="k")
    mock_post = MagicMock(return_value=_raising(httpx.ConnectError("down")))
    with _patch_post(client, mock_post):
        with pytest.raises(GatewayError, match="Failed to report edge"):
            client.report_edge("src", "dst", "messages")
