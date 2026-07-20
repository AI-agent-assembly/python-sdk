"""Benchmark init_assembly() cold-start time.

Measures the wall-clock time from calling init_assembly() to receiving
an AssemblyContext, using sdk-only mode to isolate SDK wiring overhead
from network layer startup.

The active context is reset between iterations to ensure each
measurement is a genuine cold start.
"""

from __future__ import annotations

from typing import Any

import pytest

import agent_assembly.core.assembly as assembly_mod
from agent_assembly.core.assembly import init_assembly


@pytest.fixture(autouse=True)
def _force_pure_python_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep init_assembly() hermetic whether or not the native ``_core`` extension
    is built (AAASM-4906, sibling of AAASM-4898).

    With a native ``.so`` present, ``_native_core_available()`` returns True and
    init dials a real gateway over gRPC (``connect_runtime_client`` /
    ``register_agent``); this benchmark stubs neither, so it would hang/fail.
    Forcing the pure-Python path (the CI default) keeps the measurement
    deterministic in both build modes.
    """
    monkeypatch.setattr(assembly_mod, "_native_core_available", lambda: False)


@pytest.mark.benchmark(group="init")
def test_init_assembly_coldstart(benchmark: Any) -> None:
    def cold_start() -> None:
        # Reset global state for a true cold start
        assembly_mod._ACTIVE_CONTEXT = None

        ctx = init_assembly(
            gateway_url="http://localhost:8080",
            api_key="bench-key",
            agent_id="bench-agent",
            mode="sdk-only",
        )
        ctx.shutdown()

    benchmark(cold_start)
