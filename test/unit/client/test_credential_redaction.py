"""Credential/token hygiene tests for the Python SDK (AAASM-3642).

Locks in the contract that the API key never surfaces in a ``repr`` or in a
log record — including the fire-and-forget ``EdgeEmitter`` error path, which
logs with ``exc_info=True`` and could otherwise capture httpx request/header
context. A unique sentinel is used so any leak is unambiguous.
"""

from __future__ import annotations

import logging
import threading

import pytest

from agent_assembly.client.emitter import EdgeEmitter
from agent_assembly.client.gateway import GatewayClient

SENTINEL = "SENTINEL-API-KEY-DO-NOT-LOG"


def test_repr_does_not_reveal_api_key() -> None:
    client = GatewayClient(gateway_url="http://gw.test", agent_id="a", api_key=SENTINEL)
    rendered = repr(client)
    assert SENTINEL not in rendered
    assert "<redacted>" in rendered


def test_repr_marks_absent_api_key_as_none() -> None:
    client = GatewayClient(gateway_url="http://gw.test", agent_id="a")
    assert "None" in repr(client)
    assert "<redacted>" not in repr(client)


def test_emitter_error_path_does_not_log_api_key(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The emitter's ``exc_info=True`` failure log must not contain the key.

    The emitter runs ``report_edge`` on a daemon thread and logs any exception
    with a full traceback. A realistic transport failure (no key in its own
    message) must not pull the configured ``api_key`` / ``Bearer`` header into
    the captured record — neither via the client ``repr`` nor the traceback
    frames. The sentinel key is set on the client but never appears.

    The emitter's worker thread is captured (and joined) so the assertion runs
    only after the failure log has actually been written — no flaky sleep.
    """
    client = GatewayClient(gateway_url="http://gw.test", agent_id="a", api_key=SENTINEL)

    def _raise(*_args: object, **_kwargs: object) -> dict[str, object]:
        # Realistic failure: the transport error text never embeds the key
        # (httpx does not put request headers in its exception strings).
        raise RuntimeError("connection refused")

    client.report_edge = _raise  # type: ignore[method-assign]

    captured_thread: dict[str, threading.Thread] = {}
    real_thread = threading.Thread

    def _capture_thread(*args: object, **kwargs: object) -> threading.Thread:
        t = real_thread(*args, **kwargs)  # type: ignore[arg-type]
        captured_thread["t"] = t
        return t

    monkeypatch.setattr("agent_assembly.client.emitter.threading.Thread", _capture_thread)
    emitter = EdgeEmitter(client)

    with caplog.at_level(logging.DEBUG, logger="agent_assembly.client.emitter"):
        emitter.emit("src", "dst", "messages")
        captured_thread["t"].join(timeout=2.0)

    captured = caplog.text + "".join(r.getMessage() for r in caplog.records)
    assert SENTINEL not in captured
    assert f"Bearer {SENTINEL}" not in captured
