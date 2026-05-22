"""Tests for the gateway URL / API key resolver (AAASM-1846)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from agent_assembly.core import gateway_resolver


class TestProbeHealthz:
    def test_returns_true_on_2xx_response(self) -> None:
        fake_response = MagicMock(status_code=200)
        with patch.object(gateway_resolver.httpx, "get", return_value=fake_response) as mock_get:
            assert gateway_resolver._probe_healthz("http://localhost:7391") is True

        called_url = mock_get.call_args.args[0]
        assert called_url == "http://localhost:7391/healthz"

    def test_returns_false_when_httpx_raises(self) -> None:
        with patch.object(
            gateway_resolver.httpx,
            "get",
            side_effect=httpx.ConnectError("refused"),
        ):
            assert gateway_resolver._probe_healthz("http://localhost:7391") is False

    @pytest.mark.parametrize("status", [400, 404, 500, 503])
    def test_returns_false_on_non_2xx(self, status: int) -> None:
        fake_response = MagicMock(status_code=status)
        with patch.object(gateway_resolver.httpx, "get", return_value=fake_response):
            assert gateway_resolver._probe_healthz("http://localhost:7391") is False
