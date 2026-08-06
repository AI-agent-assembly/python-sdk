"""Regression tests for ``scripts/check_readme_version.py``.

AAASM-4942: the ``--check`` flag used to be a no-op — its parsed value was
discarded and drift always forced a non-zero exit. These tests pin the two
distinct modes so the flag can't silently regress back to a single mode:
``--check`` gates (exit 1 on drift) while the default reports drift but exits 0.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_readme_version.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_readme_version", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_tree(root: Path, *, anchor: str, sample: str) -> None:
    (root / "pyproject.toml").write_text(f'[project]\nversion = "{anchor}"\n', encoding="utf-8")
    (root / "README.md").write_text(f"aasm --version   # e.g. aasm {sample}\n", encoding="utf-8")


@pytest.fixture
def script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, Path]:
    module = _load_module()
    monkeypatch.setattr(module, "_repo_root", lambda: tmp_path)
    return module, tmp_path


def test_check_exits_nonzero_on_drift(script: tuple[ModuleType, Path]) -> None:
    module, root = script
    _write_tree(root, anchor="0.0.1rc6", sample="9.9.9-STALE")

    assert module.main(["--check"]) == 1


def test_default_reports_drift_but_exits_zero(script: tuple[ModuleType, Path]) -> None:
    module, root = script
    _write_tree(root, anchor="0.0.1rc6", sample="9.9.9-STALE")

    assert module.main([]) == 0


def test_both_modes_pass_when_in_sync(script: tuple[ModuleType, Path]) -> None:
    module, root = script
    _write_tree(root, anchor="0.0.1rc6", sample="0.0.1rc6")

    assert module.main(["--check"]) == 0
    assert module.main([]) == 0
