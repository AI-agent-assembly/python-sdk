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


def test_ensure_runtime_returns_path_match_first(monkeypatch, tmp_path: Path) -> None:
    """When `aasm` is on PATH, ensure_runtime returns that resolved path."""
    import stat

    bin_dir = tmp_path / "system-bin"
    bin_dir.mkdir()
    on_path = bin_dir / _install.BINARY_NAME
    on_path.write_text("#!/bin/sh\nexit 0\n")
    on_path.chmod(on_path.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(bin_dir))

    resolved = _install.ensure_runtime()

    assert resolved == on_path


def test_ensure_runtime_falls_back_to_wheel_bundled(isolate_runtime: Path) -> None:
    """When PATH has no aasm, ensure_runtime returns the wheel-bundled path."""
    import stat

    fake_binary = isolate_runtime
    fake_binary.write_text("#!/bin/sh\nexit 0\n")
    fake_binary.chmod(fake_binary.stat().st_mode | stat.S_IXUSR)

    resolved = _install.ensure_runtime()

    assert resolved == fake_binary


def test_ensure_runtime_raises_with_install_hint(isolate_runtime: Path) -> None:
    """When no binary exists, raise RuntimeError carrying INSTALL_HINT."""
    # Sanity: isolate_runtime points at a path that doesn't exist yet.
    assert not isolate_runtime.exists()

    with pytest.raises(RuntimeError) as exc_info:
        _install.ensure_runtime()

    assert _install.INSTALL_HINT in str(exc_info.value)
