"""AAASM-5731 — a shipped governance handler must not swallow the audit record silently.

The adapters' audit hook is duck-typed and returns ``None``, so a handler that
retains the record, one that drops it, and one that never resolves the hook at
all are indistinguishable at the call site. On every interceptor this SDK ships
the hook does not resolve, so **nothing is emitted for an allowed call either** —
not just for a denied one — and before this suite there was no signal of that at
all.

Three things are pinned separately, because any one of them alone passes while
the defect is present:

1. every handler ``build_governance_interceptor`` can return, plus the LangChain
   handler that replaces it, *declares* a disposition;
2. the declaration matches behaviour in **both** directions — a handler
   declaring ``absent`` must resolve no hook and reach nothing, a handler
   declaring ``discarded`` must resolve a hook and still reach nothing, and a
   handler that genuinely records must be reported as caller-supplied;
3. ``init_assembly`` surfaces it on the DEFAULT path, with nothing opted into.

The stubs here sit at the **downstream boundaries** — the native
``RuntimeClient`` and the ``GatewayClient``'s HTTP transport — not in place of
the code under test. The point is to prove nothing crosses them. Every
"reached nothing" assertion is paired with a positive control on the same
boundary, because otherwise it is indistinguishable from a probe that never ran,
and with a forwarding control, because otherwise it is indistinguishable from a
probe that cannot see a record at all.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from typing import Any

import httpx
import pytest

from agent_assembly import init_assembly
from agent_assembly.adapters._shared.tool_governance import run_governed_async_tool
from agent_assembly.adapters.langchain.callback_handler import AssemblyCallbackHandler
from agent_assembly.client.gateway import GatewayClient
from agent_assembly.core import assembly as core_assembly
from agent_assembly.core.audit_sink import (
    AUDIT_SINK_ABSENT,
    AUDIT_SINK_CALLER_SUPPLIED,
    AUDIT_SINK_DISCARDED,
    resolve_audit_sink,
)
from agent_assembly.core.runtime_interceptor import build_governance_interceptor

from ._fake_core import FakeRuntimeClient, install_fake_core

_GW_URL = "https://gateway.test"
_API_KEY = "test-key"
_AGENT_ID = "audit-sink-agent"

# Distinctive enough that finding it anywhere downstream is unambiguous. The
# RESULT suffix is the discriminator: only the record path carries it, whereas
# the args reach the boundary on the policy check, which is the positive control.
_PROBE = "AUDIT-PROBE-AAASM-5731"
_PROBE_RESULT = f"{_PROBE}-RESULT"

# The two hook names the adapters look up, in the order they look them up.
_AUDIT_HOOKS = ("record_result", "on_tool_end")


class _RecordingRuntimeClient(FakeRuntimeClient):
    """The native boundary, recording every crossing rather than only queries."""

    def __init__(self, decision: str = "allow", reason: str = "") -> None:
        super().__init__(decision=decision, reason=reason)
        self.crossings: list[str] = []

    def query_policy(self, *args: Any, **kwargs: Any) -> dict[str, str]:
        self.crossings.append(f"query_policy:{args!r}:{kwargs!r}")
        return super().query_policy(*args, **kwargs)

    def register(self, *args: Any, **kwargs: Any) -> str:
        self.crossings.append(f"register:{args!r}")
        return super().register(*args, **kwargs)

    def send_event(self, *args: Any, **kwargs: Any) -> None:
        # Exposed by the native shim and never called from ``agent_assembly``.
        # Recorded so a future wiring change shows up here rather than silently.
        self.crossings.append(f"send_event:{args!r}")

    def __getattr__(self, name: str) -> Any:
        # Any attribute the SDK reaches for that is not defined above is still an
        # attempt to cross; record it rather than raising, so the sweep below
        # cannot miss a channel it did not anticipate.
        def _recorder(*args: Any, **kwargs: Any) -> None:
            self.crossings.append(f"{name}:{args!r}:{kwargs!r}")

        self.crossings.append(f"getattr:{name}")
        return _recorder


class _RecordingTransport(httpx.BaseTransport):
    """The HTTP boundary the GatewayClient would use."""

    def __init__(self, crossings: list[str]) -> None:
        self._crossings = crossings

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self._crossings.append(f"http:{request.method} {request.url.path} {request.content!r}")
        return httpx.Response(200, json={"edge_id": "e1"})


def _gateway_client(http_crossings: list[str]) -> GatewayClient:
    client = GatewayClient(_GW_URL, _AGENT_ID, api_key=_API_KEY)
    client._client = httpx.Client(base_url=client.gateway_url, transport=_RecordingTransport(http_crossings))
    return client


def _shipped_interceptor(
    native: Any,
    http_crossings: list[str],
    *,
    enforcement_mode: str | None = None,
    native_available: bool = True,
) -> Any:
    return build_governance_interceptor(
        _gateway_client(http_crossings),
        _AGENT_ID,
        enforcement_mode,
        runtime_client=native,
        native_available=native_available,
    )


def _run_governed(handler: Any) -> tuple[str, Any]:
    """Drive the SDK's own governed-tool chain and settle the outcome."""

    async def _go() -> Any:
        return await run_governed_async_tool(
            handler,
            enforce=True,
            tool_name="web_search",
            tool_args={"q": _PROBE},
            agent_id=_AGENT_ID,
            run_id="run-1",
            invoke_original=lambda: _PROBE_RESULT,
        )

    try:
        return "returned", asyncio.run(_go())
    except Exception as error:  # noqa: BLE001 - the deny path raises by design
        return "raised", error


def _shipped_handler_matrix(http_crossings: list[str]) -> dict[str, Any]:
    """Every handler the SDK can hand an adapter, discovered from the factory.

    Enumerated by sweeping ``build_governance_interceptor``'s own branches rather
    than by naming classes, because a name list is not a gate: a fourth branch
    returning a fourth undeclared handler would pass by omission. The LangChain
    handler is added because ``_register_adapters`` substitutes it for the
    interceptor once LangChain registers, so it is equally a shipped audit
    surface.
    """
    native = _RecordingRuntimeClient()
    handlers: dict[str, Any] = {}
    for label, kwargs in (
        ("runtime reachable, enforce", {"enforcement_mode": None}),
        ("runtime reachable, observe", {"enforcement_mode": "observe"}),
        ("runtime unreachable, enforce", {"enforcement_mode": None}),
        ("runtime unreachable, observe", {"enforcement_mode": "observe"}),
        ("native missing, enforce", {"enforcement_mode": None, "native_available": False}),
        ("native missing, observe", {"enforcement_mode": "observe", "native_available": False}),
    ):
        reachable = label.startswith("runtime reachable")
        # The native-missing enforce branch emits its own one-time warning; let
        # it through rather than letting -W error turn the sweep into a failure.
        expect_warning = "native missing, enforce" in label
        with pytest.warns(UserWarning) if expect_warning else contextlib.nullcontext():
            handler = _shipped_interceptor(
                native if reachable else None,
                http_crossings,
                **kwargs,
            )
        handlers[label] = handler
    handlers["langchain callback handler"] = AssemblyCallbackHandler(handlers["runtime reachable, enforce"])
    return handlers


def test_every_shipped_governance_handler_declares_its_audit_sink() -> None:
    handlers = _shipped_handler_matrix([])

    # Positive control on the sweep itself: it must find more than one distinct
    # handler type, or an all-pass result would only mean the sweep collapsed.
    distinct_types = {type(handler).__name__ for handler in handlers.values()}
    assert len(distinct_types) >= 3, (
        f"the factory sweep produced only {distinct_types}; it is not exercising "
        "the branches it is supposed to, so its verdict proves nothing"
    )

    undeclared = [
        label
        for label, handler in handlers.items()
        if getattr(handler, "audit_sink", None) not in {AUDIT_SINK_ABSENT, AUDIT_SINK_DISCARDED}
    ]
    assert not undeclared, (
        f"handler(s) {undeclared} are shipped without declaring what they do with the "
        "hook-layer audit record; the hook returns None either way, so a handler that "
        "records and one that emits nothing are indistinguishable (AAASM-5731)"
    )


@pytest.mark.parametrize("label", ["runtime reachable, enforce", "runtime unreachable, enforce"])
def test_a_handler_declaring_absent_resolves_no_audit_hook(label: str) -> None:
    """``absent`` means the hook does not resolve — not merely that it records nothing.

    The distinction is load-bearing: it is why the gap covers the ALLOWED path.
    The controls are on the same objects, so a blanket ``getattr`` failure cannot
    masquerade as the finding.
    """
    handlers = _shipped_handler_matrix([])
    handler = handlers[label]
    assert handler.audit_sink == AUDIT_SINK_ABSENT

    for hook in _AUDIT_HOOKS:
        assert getattr(handler, hook, None) is None, (
            f"{label} declares {AUDIT_SINK_ABSENT!r} but {hook!r} resolves on it; "
            "the declaration and the behaviour disagree"
        )

    # Positive controls on the same objects: attribute resolution works, and
    # delegation to the wrapped GatewayClient works. Without these, the four
    # `is None` assertions above are consistent with a broken probe.
    assert callable(handler.check_tool_start)
    assert callable(handler.report_edge)


@pytest.mark.parametrize("decision", ["allow", "deny"])
def test_the_shipped_path_reaches_no_boundary_with_the_record(decision: str) -> None:
    native = _RecordingRuntimeClient(decision=decision, reason="policy forbids this")
    http_crossings: list[str] = []
    handler = _shipped_interceptor(native, http_crossings)

    outcome, _value = _run_governed(handler)
    assert outcome == ("raised" if decision == "deny" else "returned")

    # Positive control: the check crossed the native boundary carrying the probe.
    assert any(_PROBE in crossing for crossing in native.crossings), (
        f"nothing carrying the probe crossed the native boundary (crossings: "
        f"{native.crossings}); the probe never ran, so the absence below proves nothing"
    )

    all_crossings = native.crossings + http_crossings
    leaked = [crossing for crossing in all_crossings if _PROBE_RESULT in crossing]
    assert not leaked, (
        f"the tool outcome reached a boundary on the shipped path: {leaked}; the "
        f"handler declares {handler.audit_sink!r}, so the declaration is wrong"
    )


def test_a_handler_that_records_does_reach_the_probe() -> None:
    """The forwarding control, in the direction the tests above cannot establish.

    Without it, "the record reached nothing" is consistent with a probe that
    cannot observe a record at all, and every absence assertion here is
    unfalsifiable.
    """
    received: list[dict[str, Any]] = []

    class _RecordingHandler:
        def check_tool_start(self, **_kwargs: Any) -> dict[str, str]:
            return {"status": "allow"}

        def record_result(self, **kwargs: Any) -> None:
            received.append(kwargs)

    handler = _RecordingHandler()
    outcome, _value = _run_governed(handler)

    assert outcome == "returned"
    assert any(_PROBE_RESULT in json.dumps(record, default=str) for record in received), (
        f"a handler whose record path genuinely resolves received nothing ({received}); "
        "the probe cannot observe a record, so every absence assertion in this file "
        "is unfalsifiable"
    )
    # This SDK must claim nothing about a handler it did not build, in either
    # direction — including one that plainly records.
    assert resolve_audit_sink(handler) == AUDIT_SINK_CALLER_SUPPLIED


def test_the_langchain_handler_resolves_the_hook_and_still_drops_the_record() -> None:
    """``discarded`` is a different failure from ``absent``, and both are shipped.

    The handler defines ``on_tool_end``, so the adapters' lookup DOES resolve and
    the record is handed over. It is then forwarded to the interceptor's own
    ``on_tool_end``, which does not exist — so the record stops here.
    """
    native = _RecordingRuntimeClient()
    http_crossings: list[str] = []
    handler = AssemblyCallbackHandler(_shipped_interceptor(native, http_crossings))

    assert handler.audit_sink == AUDIT_SINK_DISCARDED
    assert callable(handler.on_tool_end), (
        "the LangChain handler declares 'discarded', which asserts the hook RESOLVES "
        "and the record is dropped after being accepted; if no hook resolves the "
        "honest declaration is 'absent'"
    )

    baseline = len(native.crossings) + len(http_crossings)
    handler.on_tool_end(_PROBE_RESULT, run_id=uuid.uuid4())
    assert len(native.crossings) + len(http_crossings) == baseline, (
        f"on_tool_end crossed a boundary: native={native.crossings} http={http_crossings}"
    )

    # Positive control on the same handler and the same boundary.
    handler.on_tool_start({"name": "web_search"}, _PROBE, run_id=uuid.uuid4())
    assert any(_PROBE in crossing for crossing in native.crossings), (
        "the positive control did not cross either; the probe never ran"
    )


def test_init_assembly_warns_and_reports_the_audit_sink_on_the_default_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The signal must arrive with nothing opted into.

    A caller who has to already suspect the problem in order to discover it has
    not been told.
    """
    install_fake_core(monkeypatch, FakeRuntimeClient(decision="allow"))
    monkeypatch.setattr(
        core_assembly,
        "_start_network_layer",
        lambda **_kwargs: ("sdk-only", core_assembly._noop_shutdown),
    )
    core_assembly._ACTIVE_CONTEXT = None

    context = init_assembly(gateway_url=_GW_URL, api_key=_API_KEY, agent_id=_AGENT_ID, mode="sdk-only")
    try:
        stderr = capsys.readouterr().err
        assert context.audit_sink != AUDIT_SINK_CALLER_SUPPLIED
        for expected in ("audit", "NOT retained", context.audit_sink, "ALLOWED", "AAASM-5731"):
            assert expected in stderr, f"{expected!r} missing from init stderr: {stderr!r}"
    finally:
        context.shutdown()
        core_assembly._ACTIVE_CONTEXT = None
