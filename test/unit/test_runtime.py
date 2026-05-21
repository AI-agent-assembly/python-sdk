"""Unit tests for agent_assembly.runtime (AAASM-1227 / F115).

Covers the four scenarios from the AAASM-1230 AC checklist:
  * binary-in-PATH
  * binary-bundled (in agent_assembly/bin/aasm)
  * binary-not-found
  * already-running (init_assembly skips spawn when sidecar reachable)
"""

from __future__ import annotations

import os
import stat
import subprocess
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

    assert resolved == fake


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
