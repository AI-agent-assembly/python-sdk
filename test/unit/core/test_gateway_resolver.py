"""Tests for the gateway URL / API key resolver (AAASM-1846)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agent_assembly.core import gateway_resolver

_RESOLVER_MOD = "agent_assembly.core.gateway_resolver"


class TestProbeHealthz:
    def test_returns_true_on_2xx_response(self) -> None:
        fake_response = MagicMock(status_code=200)
        with patch(f"{_RESOLVER_MOD}.httpx.get", return_value=fake_response) as mock_get:
            assert gateway_resolver._probe_healthz("http://localhost:7391") is True

        called_url = mock_get.call_args.args[0]
        assert called_url == "http://localhost:7391/healthz"

    def test_returns_false_when_httpx_raises(self) -> None:
        with patch(f"{_RESOLVER_MOD}.httpx.get", side_effect=httpx.ConnectError("refused")):
            assert gateway_resolver._probe_healthz("http://localhost:7391") is False

    @pytest.mark.parametrize("status", [400, 404, 500, 503])  # type: ignore[misc]
    def test_returns_false_on_non_2xx(self, status: int) -> None:
        fake_response = MagicMock(status_code=status)
        with patch(f"{_RESOLVER_MOD}.httpx.get", return_value=fake_response):
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
            patch(f"{_RESOLVER_MOD}.time.sleep") as mock_sleep,
        ):
            result = gateway_resolver._wait_for_healthz("http://localhost:7391", timeout=5.0, poll_interval=0.01)
        assert result is True
        assert mock_sleep.call_count == 2

    def test_returns_false_when_timeout_elapses(self) -> None:
        with (
            patch.object(gateway_resolver, "_probe_healthz", return_value=False),
            patch(f"{_RESOLVER_MOD}.time.sleep"),
        ):
            result = gateway_resolver._wait_for_healthz("http://localhost:7391", timeout=0.05, poll_interval=0.01)
        assert result is False


class TestLoadConfigFile:
    def test_returns_empty_when_file_missing(self, tmp_path: Path) -> None:
        missing = tmp_path / "absent.yaml"
        assert gateway_resolver._load_config_file(str(missing)) == {}

    def test_returns_parsed_mapping(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            'agent:\n  gateway_url: "http://staging.internal:7391"\n  api_key: "k-1"\n',
            encoding="utf-8",
        )
        loaded = gateway_resolver._load_config_file(str(cfg))
        assert loaded == {"agent": {"gateway_url": "http://staging.internal:7391", "api_key": "k-1"}}

    def test_returns_empty_on_non_mapping_root(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text("- just-a-list\n", encoding="utf-8")
        assert gateway_resolver._load_config_file(str(cfg)) == {}

    def test_returns_empty_when_pyyaml_missing(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text("agent:\n  gateway_url: x\n", encoding="utf-8")
        with patch.dict("sys.modules", {"yaml": None}):
            assert gateway_resolver._load_config_file(str(cfg)) == {}


class TestAutoStartGateway:
    def test_raises_configuration_error_when_aasm_not_on_path(self) -> None:
        from agent_assembly.exceptions import ConfigurationError

        with (
            patch(f"{_RESOLVER_MOD}.shutil.which", return_value=None),
            pytest.raises(ConfigurationError, match="'aasm' is not on PATH"),
        ):
            gateway_resolver._auto_start_gateway()

    def test_spawns_subprocess_and_returns_when_ready(self) -> None:
        with (
            patch(f"{_RESOLVER_MOD}.shutil.which", return_value="/usr/local/bin/aasm"),
            patch(f"{_RESOLVER_MOD}.subprocess.Popen") as mock_popen,
            patch.object(gateway_resolver, "_wait_for_healthz", return_value=True),
        ):
            gateway_resolver._auto_start_gateway()

        args, kwargs = mock_popen.call_args
        assert args[0] == [
            "/usr/local/bin/aasm",
            "start",
            "--mode",
            "local",
            "--foreground",
        ]
        assert kwargs.get("start_new_session") is True

    def test_raises_gateway_error_on_timeout(self) -> None:
        from agent_assembly.exceptions import GatewayError

        with (
            patch(f"{_RESOLVER_MOD}.shutil.which", return_value="/usr/local/bin/aasm"),
            patch(f"{_RESOLVER_MOD}.subprocess.Popen"),
            patch.object(gateway_resolver, "_wait_for_healthz", return_value=False),
            pytest.raises(GatewayError, match="did not become ready"),
        ):
            gateway_resolver._auto_start_gateway(timeout=0.1)


class TestResolveGatewayUrl:
    def test_explicit_argument_short_circuits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(gateway_resolver.ENV_GATEWAY_URL, "http://from-env:7391")
        result = gateway_resolver.resolve_gateway_url("http://explicit:7391")
        assert result == "http://explicit:7391"

    def test_env_var_takes_precedence_over_config_and_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(gateway_resolver.ENV_GATEWAY_URL, "http://from-env:7391")
        with patch.object(
            gateway_resolver,
            "_load_config_file",
            return_value={"agent": {"gateway_url": "http://from-config:7391"}},
        ):
            assert gateway_resolver.resolve_gateway_url() == "http://from-env:7391"

    def test_config_file_used_when_env_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(gateway_resolver.ENV_GATEWAY_URL, raising=False)
        with patch.object(
            gateway_resolver,
            "_load_config_file",
            return_value={"agent": {"gateway_url": "http://from-config:7391"}},
        ):
            assert gateway_resolver.resolve_gateway_url() == "http://from-config:7391"

    def test_local_default_returned_when_probe_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(gateway_resolver.ENV_GATEWAY_URL, raising=False)
        with (
            patch.object(gateway_resolver, "_load_config_file", return_value={}),
            patch.object(gateway_resolver, "_probe_healthz", return_value=True),
            patch.object(gateway_resolver, "_auto_start_gateway") as mock_auto_start,
        ):
            assert gateway_resolver.resolve_gateway_url() == gateway_resolver.DEFAULT_GATEWAY_URL
        mock_auto_start.assert_not_called()

    def test_auto_start_invoked_when_probe_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(gateway_resolver.ENV_GATEWAY_URL, raising=False)
        with (
            patch.object(gateway_resolver, "_load_config_file", return_value={}),
            patch.object(gateway_resolver, "_probe_healthz", return_value=False),
            patch.object(gateway_resolver, "_auto_start_gateway") as mock_auto_start,
        ):
            result = gateway_resolver.resolve_gateway_url()
        assert result == gateway_resolver.DEFAULT_GATEWAY_URL
        mock_auto_start.assert_called_once_with(gateway_resolver.DEFAULT_GATEWAY_URL)


class TestResolveApiKey:
    def test_explicit_argument_short_circuits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(gateway_resolver.ENV_API_KEY, "k-env")
        assert gateway_resolver.resolve_api_key("k-explicit") == "k-explicit"

    def test_env_var_takes_precedence_over_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(gateway_resolver.ENV_API_KEY, "k-env")
        with patch.object(
            gateway_resolver,
            "_load_config_file",
            return_value={"agent": {"api_key": "k-config"}},
        ):
            assert gateway_resolver.resolve_api_key() == "k-env"

    def test_config_file_used_when_env_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(gateway_resolver.ENV_API_KEY, raising=False)
        with patch.object(
            gateway_resolver,
            "_load_config_file",
            return_value={"agent": {"api_key": "k-config"}},
        ):
            assert gateway_resolver.resolve_api_key() == "k-config"

    def test_returns_empty_string_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(gateway_resolver.ENV_API_KEY, raising=False)
        with patch.object(gateway_resolver, "_load_config_file", return_value={}):
            assert gateway_resolver.resolve_api_key() == ""
