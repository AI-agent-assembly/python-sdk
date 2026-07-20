"""AAASM-1696: agent_assembly.runtime must be importable without httpx/pydantic.

Regression test for the eager-import bug in `agent_assembly/__init__.py` that
broke aa-integration-tests::e2e_sdk_runtime_lifecycle::python_binary_in_path_returns_resolved_path
(agent-assembly run 26211782822, both ubuntu-latest and macos-latest jobs).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_python_with_blocked_imports(blocked: list[str], code: str) -> subprocess.CompletedProcess[str]:
    """Run ``code`` in a child interpreter where ``blocked`` modules raise on import."""
    block_literal = repr(blocked)
    wrapper = (
        textwrap.dedent(
            f"""
        import sys
        _BLOCKED = {block_literal}

        class _BlockingFinder:
            def find_spec(self, name, path=None, target=None):
                root = name.split(".", 1)[0]
                if root in _BLOCKED:
                    raise ModuleNotFoundError(f"No module named {{name!r}} (blocked by test)")
                return None

        sys.meta_path.insert(0, _BlockingFinder())
        """
        ).strip()
        + "\n"
        + code
    )
    return subprocess.run(
        [sys.executable, "-c", wrapper],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_runtime_import_does_not_pull_in_httpx() -> None:
    result = _run_python_with_blocked_imports(
        ["httpx", "pydantic"],
        "from agent_assembly.runtime import find_aasm_binary, init_assembly, is_running\nprint('ok')\n",
    )
    assert result.returncode == 0, (
        f"agent_assembly.runtime should not require httpx/pydantic.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert result.stdout.strip() == "ok"


def test_top_level_package_import_does_not_pull_in_httpx() -> None:
    # Import once in the test process so we know what `__version__` the
    # subprocess should print. Avoids hard-coding the literal — pre-release
    # bumps (e.g. AAASM-1933 → `0.0.1a1`) used to break this test by drift.
    import agent_assembly as _aa  # noqa: PLC0415 — test-local import on purpose

    result = _run_python_with_blocked_imports(
        ["httpx", "pydantic"],
        "import agent_assembly\nprint(agent_assembly.__version__)\n",
    )
    assert result.returncode == 0, (
        f"`import agent_assembly` must not eagerly import httpx/pydantic.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert result.stdout.strip() == _aa.__version__


def test_eager_attribute_access_still_resolves_through_lazy_loader() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import agent_assembly\n"
            "_ = agent_assembly.init_assembly\n"
            "_ = agent_assembly.AssemblyError\n"
            "_ = agent_assembly.AuditEvent\n"
            "print('ok')\n",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert result.stdout.strip() == "ok"


def test_unknown_attribute_raises_attribute_error() -> None:
    import agent_assembly

    try:
        agent_assembly.does_not_exist  # noqa: B018
    except AttributeError as exc:
        assert "does_not_exist" in str(exc)
    else:
        raise AssertionError("expected AttributeError for unknown attribute")
