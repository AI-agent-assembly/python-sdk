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


class TestWaitForHealthz:
    def test_returns_true_when_probe_succeeds_immediately(self) -> None:
        with patch.object(gateway_resolver, "_probe_healthz", return_value=True) as mock_probe:
            result = gateway_resolver._wait_for_healthz("http://localhost:7391", timeout=5.0)
        assert result is True
        assert mock_probe.call_count == 1

    def test_returns_true_after_initial_failures(self) -> None:
        probe_results = iter([False, False, True])
        with (
            patch.object(gateway_resolver, "_probe_healthz", side_effect=probe_results),
            patch.object(gateway_resolver.time, "sleep") as mock_sleep,
        ):
            result = gateway_resolver._wait_for_healthz("http://localhost:7391", timeout=5.0, poll_interval=0.01)
        assert result is True
        assert mock_sleep.call_count == 2

    def test_returns_false_when_timeout_elapses(self) -> None:
        with (
            patch.object(gateway_resolver, "_probe_healthz", return_value=False),
            patch.object(gateway_resolver.time, "sleep"),
        ):
            result = gateway_resolver._wait_for_healthz("http://localhost:7391", timeout=0.05, poll_interval=0.01)
        assert result is False
