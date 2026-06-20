"""Gateway → SDK op-control consumer (AAASM-1422 PR-E / AAASM-1654).

Subscribes to ``PolicyService.OpControlStream`` and exposes a per-``op_id``
cooperative-pause / fast-fail-terminate state machine through ``await_op``.

The subscriber runs on a daemon background thread that reads the gRPC stream
and dispatches each ``OpControlMessage`` to a per-op state slot. Application
code awaits the slot via :meth:`OpControlSubscriber.await_op`:

* ``OP_CONTROL_SIGNAL_PAUSE``  → ``await_op`` blocks until ``RESUME`` arrives.
* ``OP_CONTROL_SIGNAL_RESUME`` → ``await_op`` returns immediately.
* ``OP_CONTROL_SIGNAL_TERMINATE`` → ``await_op`` raises
  :class:`agent_assembly.exceptions.OpTerminatedError`.

If a signal arrives for an ``op_id`` no one is currently awaiting, it's
buffered into the per-op slot so the next ``await_op`` call sees it.

Wiring (AAASM-3491): a subscriber can be handed to
:func:`agent_assembly.core.runtime_interceptor.build_governance_interceptor`
(``op_control=...``); the resulting interceptor calls :meth:`await_op` for the
tool call's ``op_id`` in ``check_tool_start``, so an operator terminate/pause
reaches the running tool path. ``init_assembly`` does not construct the
subscriber automatically yet — callers opt in by passing one.

Out of scope (deferred):
  - Reconnection / heartbeat on stream close (caller observes via
    ``stream_alive`` and re-instantiates if desired).
  - Automatic construction inside ``init_assembly`` (the consumer is wired into
    the interceptor; auto-instantiation is a follow-up once the gateway-url and
    composite-id resolution at init time is settled).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Protocol

import grpc

from agent_assembly.exceptions import OpTerminatedError
from agent_assembly.proto import common_pb2, policy_pb2, policy_pb2_grpc

__all__ = ["OpControlSubscriber", "OpControlState"]


class _OpControlStub(Protocol):
    """Structural type for the gRPC stub method this module needs.

    Lets tests inject a hand-rolled stub without standing up a gRPC server.
    """

    def OpControlStream(  # noqa: N802 — gRPC method name
        self,
        request: policy_pb2.OpControlSubscribeRequest,
    ) -> Iterator[policy_pb2.OpControlMessage]: ...


@dataclass
class OpControlState:
    """Per-op state slot used by the cooperative-pause machine.

    Each ``op_id`` the subscriber observes gets one slot. ``await_op`` blocks
    on ``event`` whenever ``paused`` is set; on terminate the slot's
    ``terminated`` flag is latched and subsequent ``await_op`` calls raise
    immediately without blocking.
    """

    event: threading.Event = field(default_factory=threading.Event)
    paused: bool = False
    terminated: bool = False


class OpControlSubscriber:
    """Subscribe to OpControlStream and serve per-op pause/terminate signals.

    Construct via :meth:`connect`, never directly — the constructor takes a
    pre-wired stub so tests can mock the gRPC layer without touching the
    network.

    Thread-safe: ``await_op`` may be called from any thread; the underlying
    state is guarded by an internal ``threading.Lock``.
    """

    def __init__(self, stub: _OpControlStub, agent_id: common_pb2.AgentId) -> None:
        self._stub = stub
        self._agent_id = agent_id
        self._lock = threading.Lock()
        self._ops: dict[str, OpControlState] = {}
        self._stream_alive = threading.Event()
        self._stream_alive.set()
        self._reader: threading.Thread | None = None
        self._call: grpc.RpcContext | None = None

    @classmethod
    def connect(
        cls,
        gateway_url: str,
        *,
        org_id: str,
        team_id: str,
        agent_id: str,
        channel_factory: grpc.Channel | None = None,
    ) -> OpControlSubscriber:
        """Open the gRPC channel + subscription stream and start the reader.

        ``gateway_url`` is the ``host:port`` of the gateway's gRPC endpoint
        (no scheme; gRPC uses its own). When ``channel_factory`` is supplied
        (tests), it's used instead of opening a fresh insecure channel.
        """
        channel = channel_factory or grpc.insecure_channel(gateway_url)
        stub = policy_pb2_grpc.PolicyServiceStub(channel)  # type: ignore[no-untyped-call]
        proto_agent_id = common_pb2.AgentId(org_id=org_id, team_id=team_id, agent_id=agent_id)
        subscriber = cls(stub, proto_agent_id)
        subscriber._start()
        return subscriber

    def _start(self) -> None:
        """Open the stream + spawn the reader thread.

        Separated from ``connect`` so tests can construct a subscriber with
        a hand-rolled stub and call ``_start`` themselves.
        """
        request = policy_pb2.OpControlSubscribeRequest(agent_id=self._agent_id)
        self._call = self._stub.OpControlStream(request)
        self._reader = threading.Thread(
            target=self._reader_loop,
            name=f"aa-op-control-{self._agent_id.agent_id}",
            daemon=True,
        )
        self._reader.start()

    def _reader_loop(self) -> None:
        """Drain the stream and dispatch each message to the matching op slot."""
        try:
            for message in self._call:  # type: ignore[union-attr]
                self._dispatch(message)
        except grpc.RpcError:
            # Stream closed (server shutdown, network drop, etc.) — fall through
            # to mark the stream dead so await_op can detect it.
            pass
        finally:
            self._stream_alive.clear()
            # Wake any currently-blocked awaiters so they can re-check state.
            with self._lock:
                for state in self._ops.values():
                    state.event.set()

    def _dispatch(self, message: policy_pb2.OpControlMessage) -> None:
        """Apply one inbound signal to the per-op state slot."""
        with self._lock:
            state = self._ops.setdefault(message.op_id, OpControlState())
            signal = message.signal
            if signal == policy_pb2.OP_CONTROL_SIGNAL_PAUSE:
                state.paused = True
                state.event.clear()
            elif signal == policy_pb2.OP_CONTROL_SIGNAL_RESUME:
                state.paused = False
                state.event.set()
            elif signal == policy_pb2.OP_CONTROL_SIGNAL_TERMINATE:
                state.terminated = True
                state.event.set()

    def await_op(self, op_id: str, *, timeout: float | None = None) -> None:
        """Block until ``op_id`` is runnable, or raise on terminate.

        Returns immediately when the op is not currently paused. When paused,
        blocks on the per-op event up to ``timeout`` seconds. Raises
        :class:`OpTerminatedError` if the op has been (or becomes) terminated.

        A timeout returns normally — the caller can inspect ``is_paused`` or
        retry. This matches the cooperative-pause expectation in the
        architecture doc (the SDK yields, it doesn't deadline-enforce).
        """
        with self._lock:
            state = self._ops.setdefault(op_id, OpControlState())
            if state.terminated:
                raise OpTerminatedError(
                    f"op {op_id} was terminated by the gateway",
                    op_id=op_id,
                )
            if not state.paused:
                return
            event = state.event

        # Drop the lock while we wait so the reader thread can update state.
        event.wait(timeout=timeout)

        with self._lock:
            if state.terminated:
                raise OpTerminatedError(
                    f"op {op_id} was terminated by the gateway",
                    op_id=op_id,
                )

    def is_paused(self, op_id: str) -> bool:
        """Return True iff the gateway has the op currently paused."""
        with self._lock:
            state = self._ops.get(op_id)
            return state.paused if state else False

    def is_terminated(self, op_id: str) -> bool:
        """Return True iff the gateway has terminated the op."""
        with self._lock:
            state = self._ops.get(op_id)
            return state.terminated if state else False

    def stream_alive(self) -> bool:
        """Return False once the underlying gRPC stream has closed."""
        return self._stream_alive.is_set()

    def close(self) -> None:
        """Cancel the stream and join the reader thread."""
        if self._call is not None:
            self._call.cancel()
        if self._reader is not None:
            self._reader.join(timeout=2.0)

    def __enter__(self) -> OpControlSubscriber:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()
