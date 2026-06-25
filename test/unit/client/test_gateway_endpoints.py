"""Unit tests for the remaining `GatewayClient` HTTP endpoints.

Covers `report_edge` and the API-key auth header — the success/error paths not
already exercised by the dispatch_tool suite. The REST ``register_agent`` /
``check_policy_compliance`` methods were retired in AAASM-3402 in favor of the
native gRPC register / query_policy path, so they are no longer tested here.
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
        new_callable=lambda: property(lambda _self: MagicMock(post=mock_post)),
    )


def test_http_client_sets_bearer_auth_header_when_api_key_present() -> None:
    # allow_insecure opts past the AAASM-3725 plaintext-http refusal so this
    # test can assert header behavior on a non-loopback http:// base URL.
    client = GatewayClient(
        gateway_url="http://gw.test", agent_id="a", api_key="sekret", allow_insecure=True
    )
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
    with _patch_post(client, mock_post), pytest.raises(GatewayError, match="Failed to report edge"):
        client.report_edge("src", "dst", "messages")
