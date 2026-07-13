#!/usr/bin/env python3
"""Pre-publish guard: agent-assembly's dependency floors must co-resolve with the
supported agent frameworks.

WHY this exists (AAASM-4518): a well-meaning "pin the floor to the resolved
version" bump (AAASM-4434) raised ``pydantic``/``protobuf`` floors above what
CrewAI, Semantic Kernel, and AutoGen permit. Because the floors are metadata, the
break only surfaced *after* the wheel was published to PyPI (rc.4 is immutable) —
downstream users could no longer ``pip install agent-assembly`` alongside their
framework. This guard turns that post-publish surprise into a PR-time failure.

It resolves the SDK's *declared runtime floors* (read live from
``[project.dependencies]``) together with each framework at its current release
floor, using ``uv pip compile`` as an offline-metadata SAT solve. It never builds
or imports agent-assembly, so it is fast and runs on any platform. A floor that
excludes a framework's supported range makes the union unsatisfiable and fails the
guard, naming the conflicting constraint.

Usage::

    python scripts/ci/check_framework_resolution.py            # check current tree
    python scripts/ci/check_framework_resolution.py --python-version 3.12
    python scripts/ci/check_framework_resolution.py --pyproject path/to/pyproject.toml

Exit code 0 = every framework co-resolves; 1 = at least one conflict (details
printed); 2 = harness error (uv missing, pyproject unreadable).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

# The frameworks agent-assembly ships quick-start examples for, each pinned at the
# CURRENT release floor. The floor matters: an unconstrained `framework` lets the
# resolver pick an ancient version that trivially resolves, hiding the very conflict
# we guard against. Bump these floors when a framework's supported release moves.
# (Mirrors the frameworks called out in AAASM-4518 / examples#268.)
FRAMEWORK_MATRIX: list[str] = [
    "autogen-core>=0.7.5",  # caps protobuf<5.30
    "crewai>=1.15.2",  # caps pydantic<2.13
    "semantic-kernel>=1.30",  # caps pydantic<2.12
]

DEFAULT_PYTHON_VERSION = "3.12"  # the SDK's minimum supported interpreter


def read_runtime_floors(pyproject: Path) -> list[str]:
    """Return the ``[project.dependencies]`` specifiers verbatim from pyproject.toml."""
    with pyproject.open("rb") as fh:
        data = tomllib.load(fh)
    deps = data.get("project", {}).get("dependencies")
    if not deps:
        raise SystemExit(f"error: no [project.dependencies] found in {pyproject}")
    # Drop self-referential extras (e.g. `agent-assembly[runtime]`) — they are not
    # third-party floors and would force a build of the local project.
    return [d for d in deps if not d.replace(" ", "").startswith("agent-assembly")]


def resolve(reqs: list[str], python_version: str) -> tuple[bool, str]:
    """Try to resolve ``reqs`` together. Returns (ok, combined resolver output)."""
    with tempfile.TemporaryDirectory() as tmp:
        req_in = Path(tmp) / "req.in"
        req_out = Path(tmp) / "req.txt"
        req_in.write_text("\n".join(reqs) + "\n")
        proc = subprocess.run(
            [
                "uv",
                "pip",
                "compile",
                str(req_in),
                "--python-version",
                python_version,
                "--output-file",
                str(req_out),
                "--quiet",
                "--no-header",
            ],
            capture_output=True,
            text=True,
        )
    return proc.returncode == 0, (proc.stderr + proc.stdout).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pyproject",
        default=str(Path(__file__).resolve().parents[2] / "pyproject.toml"),
        help="path to pyproject.toml (default: repo root)",
    )
    parser.add_argument(
        "--python-version",
        default=DEFAULT_PYTHON_VERSION,
        help=f"target interpreter for resolution (default: {DEFAULT_PYTHON_VERSION})",
    )
    args = parser.parse_args()

    try:
        floors = read_runtime_floors(Path(args.pyproject))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"error: cannot read {args.pyproject}: {exc}", file=sys.stderr)
        return 2

    print("agent-assembly runtime floors under test:")
    for spec in floors:
        print(f"  {spec}")
    print(f"target python: {args.python_version}\n")

    failures: list[tuple[str, str]] = []
    for framework in FRAMEWORK_MATRIX:
        ok, output = resolve(floors + [framework], args.python_version)
        status = "OK  " if ok else "FAIL"
        print(f"[{status}] agent-assembly floors + {framework}")
        if not ok:
            failures.append((framework, output))

    if failures:
        print("\nFramework resolution conflicts (a floor excludes a supported framework):")
        for framework, output in failures:
            print(f"\n--- {framework} ---\n{output}")
        print(
            "\nRelax the offending floor to the widest range the SDK actually "
            "supports before publishing. See AAASM-4518."
        )
        return 1

    print("\nAll frameworks co-resolve with the current dependency floors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
