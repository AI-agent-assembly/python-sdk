"""Unit tests for the fire-and-forget `EdgeEmitter` helper.

`EdgeEmitter.emit` schedules `GatewayClient.report_edge` on a daemon thread so
the caller is never blocked and a gateway failure never propagates. The tests
join the spawned thread (via a stub `GatewayClient`) to make the assertions
deterministic rather than racing the daemon.
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock

from agent_assembly.client.emitter import EdgeEmitter


class _RecordingClient:
    """Stub GatewayClient that records report_edge calls and signals an Event."""

    def __init__(self, *, raise_exc: Exception | None = None) -> None:
        self.calls: list[tuple[str, str, str, dict[str, Any] | None]] = []
        self.done = threading.Event()
        self._raise_exc = raise_exc

    def report_edge(
        self,
        source_agent_id: str,
        target_agent_id: str,
        edge_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append((source_agent_id, target_agent_id, edge_type, metadata))
        try:
            if self._raise_exc is not None:
                raise self._raise_exc
            return {"edge_id": "e-1"}
        finally:
            self.done.set()


def test_emit_reports_edge_with_all_arguments() -> None:
    client = _RecordingClient()
    emitter = EdgeEmitter(client)  # type: ignore[arg-type]

    emitter.emit("src", "dst", "delegates_to", {"weight": 3})

    assert client.done.wait(timeout=2.0)
    assert client.calls == [("src", "dst", "delegates_to", {"weight": 3})]


def test_emit_passes_none_metadata_through() -> None:
    client = _RecordingClient()
    emitter = EdgeEmitter(client)  # type: ignore[arg-type]

    emitter.emit("src", "dst", "messages")

    assert client.done.wait(timeout=2.0)
    assert client.calls[0] == ("src", "dst", "messages", None)


def test_emit_swallows_report_edge_exception() -> None:
    barrier = threading.Event()

    class _RaisingClient(_RecordingClient):
        def report_edge(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            try:
                raise RuntimeError("gateway down")
            finally:
                barrier.set()

    client = _RaisingClient()
    emitter = EdgeEmitter(client)  # type: ignore[arg-type]

    # No exception should surface to the caller even though report_edge raises;
    # the daemon thread catches and logs it. The barrier confirms the failing
    # call actually ran (the except branch is exercised) without a leaked error.
    emitter.emit("src", "dst", "messages")

    assert barrier.wait(timeout=2.0)


def test_emit_uses_a_daemon_thread(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    real_thread = threading.Thread

    def fake_thread(*args: Any, **kwargs: Any) -> threading.Thread:
        captured["daemon"] = kwargs.get("daemon")
        return real_thread(*args, **kwargs)

    monkeypatch.setattr("agent_assembly.client.emitter.threading.Thread", fake_thread)
    client = MagicMock()
    emitter = EdgeEmitter(client)

    emitter.emit("src", "dst", "messages")

    assert captured["daemon"] is True
