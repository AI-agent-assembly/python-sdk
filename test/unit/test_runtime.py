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
