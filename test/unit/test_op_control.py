"""Unit tests for the OpControlSubscriber (AAASM-1422 PR-E / AAASM-1654).

The subscriber owns a background thread that reads from the gRPC stream and
dispatches signals to a per-op state machine. We exercise it by injecting a
hand-rolled stub whose ``OpControlStream`` returns a controllable iterator —
no gRPC server stood up.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from queue import Queue
from unittest.mock import patch

import pytest

from agent_assembly.exceptions import OpTerminatedError
from agent_assembly.op_control import OpControlSubscriber
from agent_assembly.proto import common_pb2, policy_pb2


class _QueueStream:
    """An iterator backed by a thread-safe queue so the test can push messages.

    Mirrors what `grpc.UnaryStreamMultiCallable.__call__` returns — an
    iterator that blocks on `next()` until a message is available, raises
    `StopIteration` when closed.
    """

    def __init__(self) -> None:
        self._q: Queue[policy_pb2.OpControlMessage | None] = Queue()
        self.cancelled = False

    def __iter__(self) -> Iterator[policy_pb2.OpControlMessage]:
        return self

    def __next__(self) -> policy_pb2.OpControlMessage:
        item = self._q.get()
        if item is None:
            raise StopIteration
        return item

    def push(self, message: policy_pb2.OpControlMessage) -> None:
        self._q.put(message)

    def end(self) -> None:
        self._q.put(None)

    def cancel(self) -> None:
        self.cancelled = True
        self.end()


class _FakeStub:
    def __init__(self, stream: _QueueStream) -> None:
        self.stream = stream
        self.last_request: policy_pb2.OpControlSubscribeRequest | None = None

    def OpControlStream(  # noqa: N802 — gRPC method name
        self,
        request: policy_pb2.OpControlSubscribeRequest,
    ) -> _QueueStream:
        self.last_request = request
        return self.stream


def _agent(name: str = "agent-7") -> common_pb2.AgentId:
    return common_pb2.AgentId(org_id="org", team_id="team", agent_id=name)


def _msg(op_id: str, signal: int, sequence: int = 0) -> policy_pb2.OpControlMessage:
    # The generated proto stub types `signal` as `OpControlSignal | str | None`,
    # but the OP_CONTROL_SIGNAL_* constants are plain ints at runtime.
    return policy_pb2.OpControlMessage(op_id=op_id, signal=signal, sequence=sequence)  # type: ignore[arg-type]


# What the `subscriber` fixture yields: the subscriber under test plus the
# queue-backed stream and stub the test drives it through.
_Subscriber = tuple[OpControlSubscriber, "_QueueStream", "_FakeStub"]


@pytest.fixture
def subscriber() -> Iterator[_Subscriber]:
    stream = _QueueStream()
    stub = _FakeStub(stream)
    sub = OpControlSubscriber(stub, _agent())
    sub._start()
    try:
        yield sub, stream, stub
    finally:
        stream.end()
        sub.close()


def test_await_op_returns_immediately_for_unknown_op(subscriber: _Subscriber) -> None:
    sub, _, _ = subscriber
    # No signal ever arrived for this op_id; await_op should be a no-op.
    sub.await_op("never-seen", timeout=0.1)


def test_pause_blocks_until_resume(subscriber: _Subscriber) -> None:
    sub, stream, _ = subscriber
    stream.push(_msg("op-1", policy_pb2.OP_CONTROL_SIGNAL_PAUSE))
    # Give the reader a moment to dispatch the pause.
    for _ in range(50):
        if sub.is_paused("op-1"):
            break
        time.sleep(0.01)
    assert sub.is_paused("op-1")

    # Start await_op in a thread; verify it blocks.
    done = threading.Event()

    def waiter() -> None:
        sub.await_op("op-1", timeout=2.0)
        done.set()

    t = threading.Thread(target=waiter)
    t.start()
    assert not done.wait(timeout=0.1), "await_op must block while paused"

    # Resume — the waiter should unblock.
    stream.push(_msg("op-1", policy_pb2.OP_CONTROL_SIGNAL_RESUME, sequence=1))
    assert done.wait(timeout=2.0), "await_op did not unblock after resume"
    t.join(timeout=1.0)
    assert not sub.is_paused("op-1")


def test_terminate_raises_op_terminated_error(subscriber: _Subscriber) -> None:
    sub, stream, _ = subscriber
    stream.push(_msg("op-2", policy_pb2.OP_CONTROL_SIGNAL_TERMINATE))
    for _ in range(50):
        if sub.is_terminated("op-2"):
            break
        time.sleep(0.01)
    assert sub.is_terminated("op-2")

    with pytest.raises(OpTerminatedError) as exc_info:
        sub.await_op("op-2", timeout=1.0)
    assert exc_info.value.op_id == "op-2"


def test_terminate_unblocks_waiter_and_raises(subscriber: _Subscriber) -> None:
    sub, stream, _ = subscriber
    stream.push(_msg("op-3", policy_pb2.OP_CONTROL_SIGNAL_PAUSE))
    for _ in range(50):
        if sub.is_paused("op-3"):
            break
        time.sleep(0.01)

    captured: list[BaseException] = []
    done = threading.Event()

    def waiter() -> None:
        try:
            sub.await_op("op-3", timeout=2.0)
        except BaseException as exc:  # noqa: BLE001 — we want to capture exactly what was raised
            captured.append(exc)
        done.set()

    t = threading.Thread(target=waiter)
    t.start()
    assert not done.wait(timeout=0.1)

    stream.push(_msg("op-3", policy_pb2.OP_CONTROL_SIGNAL_TERMINATE, sequence=1))
    assert done.wait(timeout=2.0)
    t.join(timeout=1.0)
    assert captured and isinstance(captured[0], OpTerminatedError)
    assert captured[0].op_id == "op-3"


def test_signal_for_unknown_op_is_buffered_until_first_await(subscriber: _Subscriber) -> None:
    sub, stream, _ = subscriber
    # Pause arrives before anyone is awaiting — must still be remembered.
    stream.push(_msg("op-4", policy_pb2.OP_CONTROL_SIGNAL_PAUSE))
    for _ in range(50):
        if sub.is_paused("op-4"):
            break
        time.sleep(0.01)

    # await_op should now block on the buffered pause.
    done = threading.Event()

    def waiter() -> None:
        sub.await_op("op-4", timeout=2.0)
        done.set()

    t = threading.Thread(target=waiter)
    t.start()
    assert not done.wait(timeout=0.1)

    stream.push(_msg("op-4", policy_pb2.OP_CONTROL_SIGNAL_RESUME, sequence=1))
    assert done.wait(timeout=2.0)
    t.join(timeout=1.0)


def test_subscribe_request_carries_composite_agent_id(subscriber: _Subscriber) -> None:
    _, _, stub = subscriber
    assert stub.last_request is not None
    assert stub.last_request.agent_id.org_id == "org"
    assert stub.last_request.agent_id.team_id == "team"
    assert stub.last_request.agent_id.agent_id == "agent-7"


def test_close_marks_stream_dead_and_wakes_waiters(subscriber: _Subscriber) -> None:
    sub, stream, _ = subscriber
    stream.push(_msg("op-5", policy_pb2.OP_CONTROL_SIGNAL_PAUSE))
    for _ in range(50):
        if sub.is_paused("op-5"):
            break
        time.sleep(0.01)

    done = threading.Event()

    def waiter() -> None:
        sub.await_op("op-5", timeout=2.0)
        done.set()

    t = threading.Thread(target=waiter)
    t.start()
    assert not done.wait(timeout=0.1)

    # Closing the stream should wake the waiter (without raising — close is
    # a normal lifecycle event, not a terminate).
    stream.end()
    assert done.wait(timeout=2.0)
    t.join(timeout=1.0)
    assert not sub.stream_alive()


class TestConnectTransportSecurity:
    """AAASM-3685: ``connect`` refuses plaintext gRPC to a non-loopback host."""

    def test_non_loopback_insecure_channel_rejected(self) -> None:
        # No channel_factory → connect would open grpc.insecure_channel; the
        # transport guard must refuse before that for a remote target.
        with patch("agent_assembly.op_control.grpc.insecure_channel") as mock_chan:
            with pytest.raises(ValueError, match="insecure"):
                OpControlSubscriber.connect(
                    "gateway.prod.example:443",
                    org_id="o",
                    team_id="t",
                    agent_id="a",
                )
        mock_chan.assert_not_called()

    def test_non_loopback_allowed_with_opt_in(self) -> None:
        stream = _QueueStream()
        stub = _FakeStub(stream)
        with (
            patch("agent_assembly.op_control.grpc.insecure_channel") as mock_chan,
            patch(
                "agent_assembly.op_control.policy_pb2_grpc.PolicyServiceStub",
                lambda _ch: stub,
            ),
        ):
            sub = OpControlSubscriber.connect(
                "gateway.prod.example:443",
                org_id="o",
                team_id="t",
                agent_id="a",
                allow_insecure=True,
            )
            mock_chan.assert_called_once_with("gateway.prod.example:443")
        stream.end()
        sub.close()

    def test_loopback_allowed_without_opt_in(self) -> None:
        stream = _QueueStream()
        stub = _FakeStub(stream)
        with (
            patch("agent_assembly.op_control.grpc.insecure_channel") as mock_chan,
            patch(
                "agent_assembly.op_control.policy_pb2_grpc.PolicyServiceStub",
                lambda _ch: stub,
            ),
        ):
            sub = OpControlSubscriber.connect(
                "localhost:7391",
                org_id="o",
                team_id="t",
                agent_id="a",
            )
            mock_chan.assert_called_once_with("localhost:7391")
        stream.end()
        sub.close()
