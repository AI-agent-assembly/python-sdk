"""Tests for the gateway URL / API key resolver (AAASM-1846)."""

from __future__ import annotations

import logging
import sys
import warnings
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

    @pytest.mark.parametrize("status", [400, 404, 500, 503])
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


@pytest.fixture(autouse=True)
def _reset_legacy_warn_state() -> None:
    """Clear the once-per-var deprecation guard before each test.

    The resolver tracks which legacy env vars have already warned in a
    module-level set; resetting it keeps ``pytest.warns`` assertions
    deterministic regardless of test ordering.
    """
    gateway_resolver._warned_legacy_env.clear()


class TestLegacyEnvAlias:
    def test_canonical_url_used_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(gateway_resolver.ENV_GATEWAY_URL, "http://canonical:7391")
        monkeypatch.delenv(gateway_resolver.LEGACY_ENV_GATEWAY_URL, raising=False)
        assert gateway_resolver.resolve_gateway_url() == "http://canonical:7391"

    def test_legacy_url_resolves_and_warns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(gateway_resolver.ENV_GATEWAY_URL, raising=False)
        monkeypatch.setenv(gateway_resolver.LEGACY_ENV_GATEWAY_URL, "http://legacy:7391")
        with pytest.warns(DeprecationWarning, match="AAASM_GATEWAY_URL is deprecated"):
            assert gateway_resolver.resolve_gateway_url() == "http://legacy:7391"

    def test_canonical_url_wins_when_both_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(gateway_resolver.ENV_GATEWAY_URL, "http://canonical:7391")
        monkeypatch.setenv(gateway_resolver.LEGACY_ENV_GATEWAY_URL, "http://legacy:7391")
        result = gateway_resolver.resolve_gateway_url()
        assert result == "http://canonical:7391"

    def test_no_warning_when_canonical_url_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(gateway_resolver.ENV_GATEWAY_URL, "http://canonical:7391")
        monkeypatch.setenv(gateway_resolver.LEGACY_ENV_GATEWAY_URL, "http://legacy:7391")
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            assert gateway_resolver.resolve_gateway_url() == "http://canonical:7391"

    def test_legacy_url_warns_only_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(gateway_resolver.ENV_GATEWAY_URL, raising=False)
        monkeypatch.setenv(gateway_resolver.LEGACY_ENV_GATEWAY_URL, "http://legacy:7391")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)
            gateway_resolver.resolve_gateway_url()
            gateway_resolver.resolve_gateway_url()
        deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(deprecations) == 1

    def test_canonical_key_used_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(gateway_resolver.ENV_API_KEY, "k-canonical")
        monkeypatch.delenv(gateway_resolver.LEGACY_ENV_API_KEY, raising=False)
        assert gateway_resolver.resolve_api_key() == "k-canonical"

    def test_legacy_key_resolves_and_warns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(gateway_resolver.ENV_API_KEY, raising=False)
        monkeypatch.setenv(gateway_resolver.LEGACY_ENV_API_KEY, "k-legacy")
        with pytest.warns(DeprecationWarning, match="AAASM_API_KEY is deprecated"):
            assert gateway_resolver.resolve_api_key() == "k-legacy"

    def test_canonical_key_wins_when_both_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(gateway_resolver.ENV_API_KEY, "k-canonical")
        monkeypatch.setenv(gateway_resolver.LEGACY_ENV_API_KEY, "k-legacy")
        assert gateway_resolver.resolve_api_key() == "k-canonical"

    def test_no_env_set_returns_empty_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(gateway_resolver.ENV_API_KEY, raising=False)
        monkeypatch.delenv(gateway_resolver.LEGACY_ENV_API_KEY, raising=False)
        with (
            patch.object(gateway_resolver, "_load_config_file", return_value={}),
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("error", DeprecationWarning)
            assert gateway_resolver.resolve_api_key() == ""


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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits are not meaningful on Windows")
class TestWarnIfWorldReadable:
    """Defense-in-depth permission warning for ~/.aasm/config.yaml (AAASM-4323)."""

    def test_no_warning_when_mode_is_0600(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text("agent:\n  api_key: k\n", encoding="utf-8")
        cfg.chmod(0o600)

        with caplog.at_level(logging.WARNING, logger=_RESOLVER_MOD):
            gateway_resolver._warn_if_world_readable(cfg)

        assert caplog.records == []

    def test_warns_when_mode_is_0644(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text("agent:\n  api_key: k\n", encoding="utf-8")
        cfg.chmod(0o644)

        with caplog.at_level(logging.WARNING, logger=_RESOLVER_MOD):
            gateway_resolver._warn_if_world_readable(cfg)

        assert len(caplog.records) == 1
        message = caplog.records[0].getMessage()
        assert "chmod 600" in message
        assert "644" in message
