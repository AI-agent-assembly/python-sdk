"""Unit tests for GatewayClient.dispatch_tool (AAASM-1920 Secret Injection)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from agent_assembly.client import DispatchToolResult, GatewayClient
from agent_assembly.exceptions import GatewayError


def _make_response(status_code: int = 200, payload: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload or {}
    if status_code >= 400:
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                f"{status_code}",
                request=MagicMock(),
                response=resp,
            )
        )
    else:
        resp.raise_for_status = MagicMock()
    return resp


def _patched_client(client: GatewayClient, mock_post: MagicMock) -> object:
    return patch.object(
        type(client),
        "client",
        new_callable=lambda: property(lambda _self: MagicMock(post=mock_post)),
    )


@pytest.mark.asyncio
async def test_dispatch_tool_returns_resolved_result_on_success() -> None:
    client = GatewayClient(gateway_url="http://gw.test", agent_id="agent-1", api_key="k")
    mock_post = MagicMock(
        return_value=_make_response(
            200,
            {
                "resolved_args": {"connection_string": "real-secret-abc"},
                "names_substituted": ["DB_PASSWORD"],
            },
        )
    )
    with _patched_client(client, mock_post):
        result = await client.dispatch_tool("call_database", {"connection_string": "${DB_PASSWORD}"})

    assert isinstance(result, DispatchToolResult)
    assert result.resolved_args == {"connection_string": "real-secret-abc"}
    assert result.names_substituted == ["DB_PASSWORD"]

    # Body sent over the wire is the placeholder-form — never the resolved
    # value. Pins the SDK contract complementary to the audit-shape contract
    # on the gateway side.
    _, kwargs = mock_post.call_args
    sent = kwargs.get("json") or {}
    assert sent == {"tool": "call_database", "args": {"connection_string": "${DB_PASSWORD}"}}


@pytest.mark.asyncio
async def test_dispatch_tool_raises_gateway_error_on_unknown_placeholder() -> None:
    """422 from the gateway (unknown placeholder) maps to GatewayError."""
    client = GatewayClient(gateway_url="http://gw.test", agent_id="agent-1", api_key="k")
    mock_post = MagicMock(return_value=_make_response(422))
    with _patched_client(client, mock_post), pytest.raises(GatewayError) as excinfo:
        await client.dispatch_tool("call_database", {"x": "${UNKNOWN_SECRET}"})

    assert "Failed to dispatch tool call_database" in str(excinfo.value)


@pytest.mark.asyncio
async def test_dispatch_tool_raises_gateway_error_on_network_failure() -> None:
    """Underlying httpx.ConnectError surfaces as GatewayError."""
    client = GatewayClient(gateway_url="http://gw.test", agent_id="agent-1", api_key="k")
    mock_post = MagicMock(side_effect=httpx.ConnectError("connection refused"))
    with _patched_client(client, mock_post), pytest.raises(GatewayError) as excinfo:
        await client.dispatch_tool("call_database", {"x": "y"})

    assert "Failed to dispatch tool call_database" in str(excinfo.value)


@pytest.mark.asyncio
async def test_dispatch_tool_defaults_empty_result_fields_when_server_omits_them() -> None:
    """Defensive: server returning an empty body still yields a well-formed result."""
    client = GatewayClient(gateway_url="http://gw.test", agent_id="agent-1", api_key="k")
    mock_post = MagicMock(return_value=_make_response(200, {}))
    with _patched_client(client, mock_post):
        result = await client.dispatch_tool("noop", {"x": "y"})

    assert result.resolved_args == {}
    assert result.names_substituted == []
