"""MkDocs macro adapter for the Python SDK docs (AAASM-4308).

Sources shared, drift-prone metadata (package version, package/import/CLI
names, canonical URLs, install commands) from a single source of truth and
exposes it to Markdown pages as an ``aa`` variable via ``mkdocs-macros-plugin``.

The primary source of truth is ``pyproject.toml`` (via :mod:`tomllib`); values
that are cross-repo product metadata (canonical URLs, install commands, CLI
name, import name) live in the ``aa`` dict below and are the maintainer-facing
knob for any new shared value.

Adding a new shared value
-------------------------

1. Add the value under the appropriate section of ``aa`` in ``define_env``
   (``python_sdk`` for package-authoritative facts, ``urls`` for canonical
   URLs, ``commands`` for install / CLI snippets).
2. Reference it from Markdown as ``{{ aa.<section>.<key> }}``.
3. Do not template historical release notes / changelog entries — those
   values are historical facts and must remain literal.

Fail-fast behavior
------------------

``mkdocs.yml`` enables the macros plugin with ``on_undefined: strict`` and
``on_error_fail: true`` so an undefined ``{{ aa.* }}`` reference fails the
docs build under ``mkdocs build --strict`` instead of rendering as an empty
string.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def define_env(env: Any) -> None:
    """Register the shared ``aa`` metadata variable on the macros env.

    Called by ``mkdocs-macros-plugin`` at build time. See module docstring
    for the maintainer contract when adding new shared values.
    """
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    project = pyproject["project"]

    aa: dict[str, dict[str, str]] = {
        "python_sdk": {
            "package_name": project["name"],
            "version": project["version"],
            "requires_python": project["requires-python"],
            "import_name": "agent_assembly",
            "cli_name": "aasm",
        },
        "urls": {
            "docs": "https://docs.agent-assembly.com/python-sdk/",
            "repo": "https://github.com/ai-agent-assembly/python-sdk",
            "pypi": "https://pypi.org/project/agent-assembly/",
        },
        "commands": {
            "install_uv": "uv add agent-assembly",
            "install_pip": "pip install agent-assembly",
            "install_pip_runtime": "pip install 'agent-assembly[runtime]'",
        },
    }

    env.variables["aa"] = aa
