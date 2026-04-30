from __future__ import annotations

import os
import subprocess
import sys

import pytest


@pytest.mark.integration
def test_maturin_develop_exposes_runtime_client() -> None:
    if os.getenv("AAASM_RUN_MATURIN_TESTS") != "1":
        pytest.skip("Set AAASM_RUN_MATURIN_TESTS=1 to run maturin integration smoke tests.")

    command = [
        "uv",
        "tool",
        "run",
        "maturin",
        "develop",
        "--manifest-path",
        "rust/aa-ffi-python/Cargo.toml",
        "--release",
    ]
    env = os.environ.copy()
    env.setdefault("PYO3_USE_ABI3_FORWARD_COMPATIBILITY", "1")
    subprocess.run(command, check=True, env=env)

    from agent_assembly._core import RuntimeClient

    assert RuntimeClient is not None
    assert hasattr(RuntimeClient, "connect")
    assert sys.modules.get("agent_assembly._core") is not None
