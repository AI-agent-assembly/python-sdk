"""Unit tests for agent_assembly._install — install-time runtime resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_assembly import _install


@pytest.fixture
def isolate_runtime(monkeypatch, tmp_path: Path) -> Path:
    """Isolate ensure_runtime() from the host environment.

    Yields a context where:
      - PATH is empty (so ``shutil.which`` cannot find any system binary).
      - ``WHEEL_BUNDLED_BIN`` points at ``tmp_path/bin/aasm`` (missing by
        default; tests opt in by creating the file).
    """
    fake_bin_dir = tmp_path / "bin"
    fake_bin_dir.mkdir()
    fake_binary = fake_bin_dir / _install.BINARY_NAME
    monkeypatch.setattr(_install, "WHEEL_BUNDLED_BIN", fake_binary)
    monkeypatch.setenv("PATH", "")
    return fake_binary
