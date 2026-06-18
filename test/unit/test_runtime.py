"""Unit tests for agent_assembly.runtime (AAASM-1227 / F115).

Covers the four scenarios from the AAASM-1230 AC checklist:
  * binary-in-PATH
  * binary-bundled (in agent_assembly/bin/aasm)
  * binary-not-found
  * already-running (init_assembly skips spawn when sidecar reachable)
"""

from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_assembly import runtime


def _make_fake_aasm(directory: Path) -> Path:
    """Write an executable `aasm` shim into ``directory`` and return its path."""
    path = directory / runtime.BINARY_NAME
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def test_find_aasm_binary_returns_path_hit_when_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """binary-in-PATH: shutil.which hit returns immediately, ahead of every fallback."""
    fake = _make_fake_aasm(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path))

    resolved = runtime.find_aasm_binary()

    assert resolved == fake  # noqa: S101 — pytest assertion


def test_init_assembly_raises_runtime_error_with_install_hint_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """binary-not-found: init_assembly raises RuntimeError whose message is the
    INSTALL_HINT (which includes the pip/brew/curl copy-paste commands)."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.setenv("PATH", str(empty_dir))
    monkeypatch.setattr(runtime, "USER_LOCAL_BIN", tmp_path / "no-such-local-bin")
    monkeypatch.setattr(runtime, "WHEEL_BUNDLED_BIN", tmp_path / "no-such-wheel-bin")
    monkeypatch.setattr(runtime, "DOCKER_BASE_BIN", tmp_path / "no-such-docker-bin")
    # Ensure is_running returns False so the orchestrator reaches find_aasm_binary.
    monkeypatch.setattr(runtime, "is_running", lambda *_args, **_kw: False)

    with pytest.raises(RuntimeError) as exc_info:
        runtime.init_assembly()

    assert str(exc_info.value) == runtime.INSTALL_HINT
    assert "agent-assembly runtime not found" in str(exc_info.value)
    assert "pip install" in str(exc_info.value)


def test_find_aasm_binary_returns_wheel_bundled_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """binary-bundled: when PATH and ~/.local/bin both miss, the wheel-bundled
    location (`agent_assembly/bin/aasm`) is the next checked fallback."""
    fake_wheel_bin = tmp_path / "wheel_bin"
    fake_wheel_bin.mkdir()
    fake = _make_fake_aasm(fake_wheel_bin)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))  # not on PATH
    monkeypatch.setattr(runtime, "USER_LOCAL_BIN", tmp_path / "no-such-local-bin")
    monkeypatch.setattr(runtime, "WHEEL_BUNDLED_BIN", fake_wheel_bin)
    monkeypatch.setattr(runtime, "DOCKER_BASE_BIN", tmp_path / "no-such-docker-bin")

    resolved = runtime.find_aasm_binary()

    assert resolved == fake


def test_init_assembly_idempotent_when_already_running(monkeypatch: pytest.MonkeyPatch) -> None:
    """already-running: init_assembly returns early without calling
    find_aasm_binary or start_runtime when is_running reports True."""
    find_spy = MagicMock(return_value=None)
    start_spy = MagicMock()
    monkeypatch.setattr(runtime, "is_running", lambda *_args, **_kw: True)
    monkeypatch.setattr(runtime, "find_aasm_binary", find_spy)
    monkeypatch.setattr(runtime, "start_runtime", start_spy)

    runtime.init_assembly()

    find_spy.assert_not_called()
    start_spy.assert_not_called()


def test_is_running_true_when_listener_accepts(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful connect on host:port reports the sidecar as up."""

    class _FakeConn:
        def __enter__(self) -> _FakeConn:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(
        runtime.socket,
        "create_connection",
        lambda address, timeout: _FakeConn(),
    )

    assert runtime.is_running(port=7878) is True


def test_is_running_false_on_socket_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any OSError (refused / timeout / unreachable) means no sidecar."""

    def refuse(address: object, timeout: object) -> object:
        raise ConnectionRefusedError("nothing listening")

    monkeypatch.setattr(runtime.socket, "create_connection", refuse)

    assert runtime.is_running(port=7878) is False


def test_start_runtime_spawns_detached_serve_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """start_runtime opens the log file in the chosen dir and spawns the
    detached ``aasm serve --port`` subprocess with stdout/stderr redirected."""
    captured: dict[str, object] = {}

    def fake_popen(cmd: list[str], **kwargs: object) -> str:
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return "popen-handle"

    monkeypatch.setattr(runtime.subprocess, "Popen", fake_popen)

    handle = runtime.start_runtime(Path("/bin/aasm"), port=9001, log_dir=tmp_path)

    assert handle == "popen-handle"
    assert captured["cmd"] == ["/bin/aasm", "serve", "--port", "9001"]
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["start_new_session"] is True
    # The runtime log file is created in the supplied log_dir.
    assert (tmp_path / runtime.RUNTIME_LOG_FILENAME).exists()


def test_init_assembly_spawns_when_not_running(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the sidecar is down and a binary exists, init_assembly resolves the
    binary and starts the runtime exactly once."""
    binary = Path("/usr/local/bin/aasm")
    start_spy = MagicMock()
    monkeypatch.setattr(runtime, "is_running", lambda *_a, **_kw: False)
    monkeypatch.setattr(runtime, "find_aasm_binary", lambda: binary)
    monkeypatch.setattr(runtime, "start_runtime", start_spy)

    runtime.init_assembly(agent_id="ignored-at-this-layer", port=7878)

    start_spy.assert_called_once_with(binary, port=7878)
