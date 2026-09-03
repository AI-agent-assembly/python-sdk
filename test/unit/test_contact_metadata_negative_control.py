"""Negative controls for ``scripts/check_contact_metadata.py`` (AAASM-5756).

AAASM-5756 (Epic AAASM-5519, parent AC#4): the gate that syncs
``SECURITY.md``/``pyproject.toml`` against the pinned canonical registry must
fail closed — a dropped generated region or a drifted value must turn the
``--check`` gate red, not silently pass. Each case here writes a fixture copy
of the real consumer files into ``tmp_path`` (via the script's own ``--root``
override, AAASM-5756), mutates exactly one thing, and calls the script's
``main()`` directly to assert the resulting exit code.

Exit codes exercised (read from the script's own ``sys.exit``/``return``
sites, not assumed):

* ``0`` — in sync with the pinned registry.
* ``1`` — ``--check`` mode, a consumer file's synced content differs from
  what is on disk (value drift): ``main()``'s ``drifted`` branch under
  ``args.check``.
* ``2`` — a consumed file cannot be read or is structurally wrong
  (``ContactDriftError``/``OSError``/``FileNotFoundError``): the region
  markers are missing, or the ``pyproject.toml`` author-email regex does not
  match exactly once. This is the fail-closed path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_contact_metadata.py"
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_contact_metadata", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_clean_tree(root: Path) -> None:
    """Copy the repo's real consumer files into ``root`` byte-for-byte."""
    (root / "SECURITY.md").write_text((_REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8"), encoding="utf-8")
    (root / "pyproject.toml").write_text((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"), encoding="utf-8")


def test_clean_copy_passes_the_check(tmp_path: Path) -> None:
    module = _load_module()
    _write_clean_tree(tmp_path)

    assert module.main(["--check", "--root", str(tmp_path)]) == 0


def test_dropped_begin_sentinel_fails_closed(tmp_path: Path) -> None:
    """AC#4: removing the generated region's sentinel turns the gate red.

    This is the case the parent ticket's AC#4 requires to unambiguously
    exist — the generated region is gone, so the gate must not exit 0.
    """
    module = _load_module()
    _write_clean_tree(tmp_path)
    security = tmp_path / "SECURITY.md"
    text = security.read_text(encoding="utf-8")
    mutated = text.replace("<!-- BEGIN GENERATED: security_contact -->\n", "")
    assert mutated != text
    security.write_text(mutated, encoding="utf-8")

    assert module.main(["--check", "--root", str(tmp_path)]) == 2


def test_whole_generated_block_deleted_fails_closed(tmp_path: Path) -> None:
    """AC#4: deleting both sentinels and the body also turns the gate red."""
    module = _load_module()
    _write_clean_tree(tmp_path)
    security = tmp_path / "SECURITY.md"
    text = security.read_text(encoding="utf-8")
    begin = text.index("<!-- BEGIN GENERATED: security_contact -->")
    end = text.index("<!-- END GENERATED: security_contact -->") + len("<!-- END GENERATED: security_contact -->\n")
    mutated = text[:begin] + text[end:]
    assert mutated != text
    security.write_text(mutated, encoding="utf-8")

    assert module.main(["--check", "--root", str(tmp_path)]) == 2


def test_legacy_domain_swapped_into_the_generated_block_is_drift(tmp_path: Path) -> None:
    module = _load_module()
    _write_clean_tree(tmp_path)
    security = tmp_path / "SECURITY.md"
    text = security.read_text(encoding="utf-8")
    mutated = text.replace(
        "Report security vulnerabilities privately to **security@agent-assembly.com**.",
        "Report security vulnerabilities privately to **security@agent-assembly.dev**.",
    )
    assert mutated != text
    security.write_text(mutated, encoding="utf-8")

    assert module.main(["--check", "--root", str(tmp_path)]) == 1


def test_sla_day_count_edited_is_drift(tmp_path: Path) -> None:
    module = _load_module()
    _write_clean_tree(tmp_path)
    security = tmp_path / "SECURITY.md"
    text = security.read_text(encoding="utf-8")
    mutated = text.replace("Within 2 business days", "Within 3 business days")
    assert mutated != text
    security.write_text(mutated, encoding="utf-8")

    assert module.main(["--check", "--root", str(tmp_path)]) == 1


def test_duplicated_pyproject_author_email_fails_closed_count_guard(tmp_path: Path) -> None:
    """A second ``authors = [{...email=...}]`` breaks the exactly-one-match
    invariant the script's fail-closed regex sync relies on."""
    module = _load_module()
    _write_clean_tree(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    original_line = 'authors = [{ name = "Agent Assembly Team", email = "team@agent-assembly.com" }]'
    assert original_line in text
    duplicated_line = 'authors = [{ name = "Duplicate Author", email = "other@agent-assembly.com" }]'
    mutated = text.replace(original_line, f"{original_line}\n{duplicated_line}")
    assert mutated != text
    pyproject.write_text(mutated, encoding="utf-8")

    assert module.main(["--check", "--root", str(tmp_path)]) == 2
