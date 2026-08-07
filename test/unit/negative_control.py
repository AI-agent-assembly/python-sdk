"""Reusable enforcement-truth negative-control fixture (AAASM-5529).

A test that only asserts ``pytest.raises(PolicyViolationError)`` proves the SDK
produced a refusal, not that the refusal *prevented* anything: a tool whose body
has no observable effect would satisfy the same assertion. These helpers give a
denied tool a real, externally-observable effect — a file on disk, an HTTP
request delivered to a live loopback listener — so a deny can be asserted as the
*absence* of that effect and the matching allow as its *presence*.

Every control built on this fixture is used as a pair:

* **positive control** — policy allows, the effect is observed. Without it,
  "no file on disk" is equally well explained by "the tool never ran at all",
  and the negative control proves nothing.
* **negative control** — policy denies, the same effect is absent.

The effects are deliberately real (``pathlib``, ``http.server``) rather than
``Mock`` call counters: a recorded call is evidence of intent, and Epic
AAASM-5526 exists because intent-level evidence is what over-claimed enforcement
looks like.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib import request as urllib_request


@dataclass
class FileSideEffect:
    """A filesystem-backed side effect rooted at ``path``.

    ``write`` really creates the file and ``occurred`` really stats it, so an
    assertion over ``occurred()`` is an assertion about the world rather than
    about the SDK's own bookkeeping.
    """

    path: Path

    def write(self, content: str) -> str:
        self.path.write_text(content, encoding="utf-8")
        return str(self.path)

    def occurred(self) -> bool:
        return self.path.exists()

    def content(self) -> str | None:
        if not self.path.exists():
            return None
        return self.path.read_text(encoding="utf-8")


@dataclass
class ReceivedRequest:
    method: str
    path: str
    body: str


class _RecordingHandler(BaseHTTPRequestHandler):
    """Records every request instead of serving anything."""

    received: list[ReceivedRequest]

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else ""
        type(self).received.append(ReceivedRequest(method="POST", path=self.path, body=body))
        self.send_response(204)
        self.end_headers()

    def log_message(self, _format: str, *_args: Any) -> None:
        """Silence the default stderr access log so test output stays readable."""
        return None


@dataclass
class NetworkSideEffect:
    """A loopback HTTP listener that records every request it receives.

    A denied tool must leave ``requests`` empty. Because the positive control
    exercises the same live listener, an empty log is evidence the egress did
    not happen rather than evidence it could not have.
    """

    url: str
    _server: HTTPServer
    _thread: threading.Thread
    requests: list[ReceivedRequest] = field(default_factory=list)

    def call(self, body: str) -> int:
        req = urllib_request.Request(self.url, data=body.encode("utf-8"), method="POST")
        with urllib_request.urlopen(req, timeout=5) as response:  # noqa: S310 - fixed loopback URL
            return int(response.status)

    def occurred(self) -> bool:
        return len(self.requests) > 0

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def start_network_side_effect() -> NetworkSideEffect:
    """Start a loopback listener on an ephemeral port and return its fixture."""
    received: list[ReceivedRequest] = []
    handler = type("_BoundRecordingHandler", (_RecordingHandler,), {"received": received})
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return NetworkSideEffect(
        url=f"http://127.0.0.1:{server.server_port}/exfiltrate",
        _server=server,
        _thread=thread,
        requests=received,
    )


@dataclass
class RecordedResult:
    """One audit record the governed path emitted.

    ``denied`` separates "denied before execution" from a tool that ran and
    returned the denial text — on the denied path ``result`` carries the
    policy-violation message, so the flag is what makes the two distinguishable.
    """

    tool_name: str
    agent_id: str | None
    run_id: str | None
    result: str
    denied: bool = False


class AuditRecordingInterceptor:
    """Delegates every governance call to ``inner`` and records the audit hook.

    Only the post-execution ``record_result`` hook is added — the authoritative
    verdict still comes from the wrapped interceptor, so the deny under test is
    the real one.

    ``record_result`` is a hook the SDK genuinely calls, not a fixture
    invention: ``_shared.tool_governance._record_async_tool_result`` duck-types
    it on the callback handler (with an ``on_tool_end`` fallback), and seven
    adapters route through it. The fixture supplies it because the real
    ``GatewayClient`` implements no audit sink of its own — it exposes only
    ``report_edge`` — so without a handler that accepts the hook there is
    nothing to read the record off.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.records: list[RecordedResult] = []

    def check_tool_start(self, **kwargs: Any) -> Any:
        return self._inner.check_tool_start(**kwargs)

    def record_result(
        self,
        *,
        tool_name: str,
        result: str,
        agent_id: str | None = None,
        run_id: str | None = None,
        denied: bool = False,
    ) -> None:
        self.records.append(
            RecordedResult(
                tool_name=tool_name,
                agent_id=agent_id,
                run_id=run_id,
                result=result,
                denied=denied,
            )
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def tool_args_of(query_call: tuple[Any, ...]) -> dict[str, Any]:
    """Decode the ``tool_args_json`` the SDK presented to the native runtime.

    ``FakeRuntimeClient.query_calls`` entries are
    ``(agent_id, action_type, tool_name, tool_args_json)``.
    """
    raw = query_call[3]
    if not raw:
        return {}
    decoded = json.loads(raw)
    return decoded if isinstance(decoded, dict) else {}
