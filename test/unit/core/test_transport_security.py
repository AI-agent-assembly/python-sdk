"""Tests for the shared transport-security validator (AAASM-3685/3725)."""

from __future__ import annotations

import warnings

import pytest

from agent_assembly.core import transport_security as ts


class TestGatewayHostOf:
    @pytest.mark.parametrize(
        ("target", "expected"),
        [
            ("localhost:7391", "localhost"),
            ("127.0.0.1:7391", "127.0.0.1"),
            ("http://localhost:7391", "localhost"),
            ("https://gw.prod.example/path", "gw.prod.example"),
            ("gw.prod.example:443", "gw.prod.example"),
            ("[::1]:7391", "[::1]"),
            ("[::1]", "[::1]"),
            ("user:pass@gw.prod.example:443", "gw.prod.example"),
            ("LOCALHOST:7391", "localhost"),
            ("bare-host", "bare-host"),
        ],
    )
    def test_extracts_host(self, target: str, expected: str) -> None:
        assert ts.gateway_host_of(target) == expected


class TestIsLoopbackTarget:
    @pytest.mark.parametrize(
        "target",
        ["localhost:7391", "127.0.0.1:7391", "http://localhost:7391", "[::1]:7391", "::1"],
    )
    def test_loopback(self, target: str) -> None:
        assert ts.is_loopback_target(target) is True

    @pytest.mark.parametrize(
        "target",
        ["gw.prod.example:443", "http://gw.test", "10.0.0.5:7391", "example.com"],
    )
    def test_non_loopback(self, target: str) -> None:
        assert ts.is_loopback_target(target) is False


class TestRequireSecureGrpcTarget:
    def test_loopback_allowed(self) -> None:
        ts.require_secure_grpc_target("localhost:7391", allow_insecure=False)

    def test_non_loopback_rejected_without_opt_in(self) -> None:
        with pytest.raises(ValueError, match="insecure"):
            ts.require_secure_grpc_target("gw.prod.example:443", allow_insecure=False)

    def test_non_loopback_allowed_with_opt_in(self) -> None:
        ts.require_secure_grpc_target("gw.prod.example:443", allow_insecure=True)


class TestRequireSecureHttpUrl:
    def test_https_always_allowed(self) -> None:
        ts.require_secure_http_url("https://gw.test", has_api_key=True, allow_insecure=False)

    def test_http_no_key_allowed(self) -> None:
        ts.require_secure_http_url("http://gw.test", has_api_key=False, allow_insecure=False)

    def test_loopback_http_with_key_allowed(self) -> None:
        ts.require_secure_http_url("http://localhost:7391", has_api_key=True, allow_insecure=False)

    def test_non_loopback_http_with_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="Bearer"):
            ts.require_secure_http_url("http://gw.test", has_api_key=True, allow_insecure=False)

    def test_non_loopback_http_with_key_allowed_when_opted_in(self) -> None:
        ts.require_secure_http_url("http://gw.test", has_api_key=True, allow_insecure=True)


class TestWarnIfInsecureHttpUrl:
    def test_warns_on_non_loopback_http_with_key(self) -> None:
        with pytest.warns(UserWarning, match="unencrypted"):
            ts.warn_if_insecure_http_url("http://gw.test", has_api_key=True)

    @pytest.mark.parametrize(
        ("url", "has_key"),
        [
            ("https://gw.test", True),
            ("http://gw.test", False),
            ("http://localhost:7391", True),
        ],
    )
    def test_silent_otherwise(self, url: str, has_key: bool) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            ts.warn_if_insecure_http_url(url, has_api_key=has_key)
