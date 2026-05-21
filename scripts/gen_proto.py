#!/usr/bin/env python3
"""Regenerate Python proto stubs from the sibling agent-assembly checkout.

AAASM-1654 (PR-E of AAASM-1422). Generates only the protos this SDK
actually consumes today (policy + common). The output lives under
``agent_assembly/proto/`` and is committed to the repo so users don't
need ``grpcio-tools`` at runtime.

Usage::

    .venv/bin/python scripts/gen_proto.py
    # or with a non-default sibling location:
    AA_PROTO_DIR=/some/other/agent-assembly/proto .venv/bin/python scripts/gen_proto.py

A drift check that runs this script in CI and asserts no diff is left
as a follow-up hygiene sub-task.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

# Per memory `project_sibling_repo_ci_pattern`: cross-repo deps use
# sibling-checkout via env vars. Default mirrors the workspace layout
# ($REPO_PARENT/agent-assembly/proto).
DEFAULT_PROTO_DIR = Path(__file__).resolve().parent.parent.parent / "agent-assembly" / "proto"

# Only generate the protos the SDK actually consumes. Keeping the set
# tight keeps the committed-stubs diff readable and avoids accidentally
# coupling the SDK to RPCs it doesn't use.
PROTO_FILES = ["common.proto", "policy.proto"]

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "agent_assembly" / "proto"


def main() -> int:
    proto_dir = Path(os.environ.get("AA_PROTO_DIR", DEFAULT_PROTO_DIR)).resolve()
    if not proto_dir.is_dir():
        print(f"error: proto dir {proto_dir} does not exist", file=sys.stderr)
        print("Set AA_PROTO_DIR to the agent-assembly/proto location.", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "__init__.py").touch(exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"--proto_path={proto_dir}",
        f"--python_out={OUTPUT_DIR}",
        f"--pyi_out={OUTPUT_DIR}",
        f"--grpc_python_out={OUTPUT_DIR}",
        *[str(proto_dir / name) for name in PROTO_FILES],
    ]
    print(f"running: {' '.join(cmd)}")
    rc = subprocess.run(cmd, check=False).returncode
    if rc != 0:
        return rc

    # grpcio-tools emits sibling-relative imports (`import common_pb2`) which
    # break under Python's normal package import mechanics. Rewrite them to
    # explicit relative imports (`from . import common_pb2`) so the
    # generated stubs work from `agent_assembly.proto`. Pattern is conservative
    # — only the top-level `import xxx_pb2(_grpc)?` lines are rewritten.
    pattern = re.compile(r"^import (\w+_pb2(?:_grpc)?) as (\w+)$", re.MULTILINE)
    for py in OUTPUT_DIR.glob("*_pb2*.py"):
        text = py.read_text()
        new_text = pattern.sub(r"from . import \1 as \2", text)
        if new_text != text:
            py.write_text(new_text)
            print(f"  rewrote sibling imports in {py.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
