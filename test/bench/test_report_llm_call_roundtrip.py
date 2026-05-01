"""Benchmark report_llm_call() PyO3 round-trip overhead.

Measures the Python-to-Rust boundary crossing overhead for
governance event reporting via the native `_core` module.

This benchmark is conditional — it is skipped when the native
module has not been built (requires `maturin develop`).

Contract: per-call overhead must be <2ms P99 (AAASM-45).
"""

from __future__ import annotations

import json
from typing import Any

import pytest


@pytest.mark.benchmark(group="ffi")
def test_governance_event_construction(benchmark: Any) -> None:
    """Benchmark GovernanceEvent PyO3 construction (JSON deserialization)."""
    _core = pytest.importorskip(
        "agent_assembly._core",
        reason="native _core module not built (requires maturin develop)",
    )

    payload = json.dumps(
        {
            "event_type": "LlmCall",
            "agent_id": "bench-agent",
            "tool_name": "bench-tool",
            "input": "benchmark input",
            "output": "benchmark output",
            "timestamp": "2026-01-01T00:00:00Z",
            "duration_ms": 100,
        }
    )

    def construct() -> Any:
        return _core.GovernanceEvent(payload)

    benchmark(construct)


@pytest.mark.benchmark(group="ffi")
def test_send_event_enqueue(benchmark: Any) -> None:
    """Benchmark RuntimeClient.send_event() channel enqueue overhead.

    Uses a connected RuntimeClient pointed at a non-existent socket.
    The worker will fail to connect but the channel send (Python→Rust
    boundary + mpsc enqueue) is still measured. Events are fire-and-forget
    so the enqueue completes immediately.
    """
    _core = pytest.importorskip(
        "agent_assembly._core",
        reason="native _core module not built (requires maturin develop)",
    )

    payload = json.dumps(
        {
            "event_type": "LlmCall",
            "agent_id": "bench-agent",
            "tool_name": "bench-tool",
            "input": "benchmark input",
            "output": "benchmark output",
            "timestamp": "2026-01-01T00:00:00Z",
            "duration_ms": 100,
        }
    )
    event = _core.GovernanceEvent(payload)

    # connect() spawns a background worker; send_event() enqueues to the
    # mpsc channel without blocking on IPC delivery.
    client = _core.RuntimeClient.connect("/tmp/aa-bench-nonexistent.sock")

    def send() -> None:
        try:
            client.send_event(event)
        except RuntimeError:
            # Worker may close the channel after failing to connect —
            # the benchmark still captures the Python→PyO3 boundary cost.
            pass

    benchmark(send)
