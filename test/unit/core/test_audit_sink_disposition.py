"""AAASM-5731 / AAASM-5750 — what a shipped governance handler does with the audit record.

The adapters' audit hook is duck-typed and returns ``None``, so a handler that
forwards the record, one that drops it, and one that never resolves the hook at
all are indistinguishable at the call site. Over a connected runtime the SDK's
interceptor now resolves the hook and sends the record across the native
boundary; without one no hook resolves and **nothing is emitted for an allowed
call either** — not just for a denied one.

Three things are pinned separately, because any one of them alone passes while a
defect is present:

1. every handler ``build_governance_interceptor`` can return, plus the LangChain
   handler that replaces it, *declares* a disposition;
2. the declaration matches behaviour in **both** directions — a handler
   declaring ``forwarded`` must reach the native boundary with the record, one
   declaring ``absent`` must resolve no hook and reach nothing, one declaring
   ``discarded`` must resolve a hook and still reach nothing, and a handler that
   genuinely records must be reported as caller-supplied;
3. ``init_assembly`` surfaces the gap on the DEFAULT path, with nothing opted
   into, and stays quiet when there is no gap.

The stubs here sit at the **downstream boundaries** — the native
``RuntimeClient`` and the ``GatewayClient``'s HTTP transport — not in place of
the code under test. Nothing here injects a sink into the SDK's own path: a suite
that supplies its own recording handler proves that handler records and stays
green over an interceptor wired to nothing, which is the defect AAASM-5749 found
one row over. Every claim about a boundary is paired with a positive control on
the same boundary, because otherwise it is indistinguishable from a probe that
never ran.
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
    AUDIT_SINK_FORWARDED,
    resolve_audit_sink,
    resolve_delegated_audit_sink,
)
from agent_assembly.core.runtime_audit import build_tool_outcome_payload
from agent_assembly.core.runtime_interceptor import (
    RuntimeQueryInterceptor,
    build_governance_interceptor,
)

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
        # The audit sink. Recorded as its payload JSON rather than the wrapper's
        # repr, because the assertions below look for the probe INSIDE the
        # record and a default object repr would hide it.
        payloads = [getattr(arg, "payload_json", arg) for arg in args]
        self.crossings.append(f"send_event:{payloads!r}")

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


def _declares_on_its_own_class(handler: object) -> bool:
    """Whether ``audit_sink`` is declared in the handler's own MRO.

    ``getattr`` cannot answer this: every interceptor here defines ``__getattr__``
    and would happily forward the lookup to the wrapped client, which is exactly
    the hole this closes. A class-dictionary walk is consulted instead, because
    instance ``__getattr__`` is not invoked for attributes found on the class.
    """
    return any("audit_sink" in klass.__dict__ for klass in type(handler).__mro__ if klass is not object)


def test_the_declaration_probe_can_tell_delegation_from_declaration() -> None:
    """Control for _declares_on_its_own_class, which the gate's verdict rests on.

    Without it, a probe that returned True unconditionally would make the gate
    above pass for every handler, including one that only delegates.
    """

    class _Delegating:
        def __init__(self, inner: object) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    class _Declaring:
        audit_sink = AUDIT_SINK_ABSENT

    declaring = _Declaring()
    delegating = _Delegating(declaring)

    # The delegating object answers the same value, and must still be rejected.
    assert getattr(delegating, "audit_sink", None) == AUDIT_SINK_ABSENT
    assert _declares_on_its_own_class(declaring) is True
    assert _declares_on_its_own_class(delegating) is False


def test_every_shipped_governance_handler_declares_its_audit_sink() -> None:
    handlers = _shipped_handler_matrix([])

    # Positive control on the sweep itself: it must find more than one distinct
    # handler type, or an all-pass result would only mean the sweep collapsed.
    distinct_types = {type(handler).__name__ for handler in handlers.values()}
    assert len(distinct_types) >= 3, (
        f"the factory sweep produced only {distinct_types}; it is not exercising "
        "the branches it is supposed to, so its verdict proves nothing"
    )

    # Every handler must declare on ITS OWN class, not inherit an answer through
    # __getattr__. Review of #315 measured why: deleting audit_sink from
    # RuntimeQueryInterceptor left __getattr__ answering from GatewayClient and
    # all eight tests passed, so the interceptor was never required to speak for
    # itself — and a fourth interceptor that delegates would inherit "absent"
    # silently even if its own hook resolved.
    silent = [label for label, handler in handlers.items() if not _declares_on_its_own_class(handler)]
    assert not silent, (
        f"handler(s) {silent} do not declare 'audit_sink' anywhere in their own MRO; "
        "they answer only by delegation, so the gate would pass a handler that never "
        "says what it does with the record (AAASM-5731)"
    )

    # Assert the SET this matrix produces, not membership of the whole vocabulary.
    # The four-value acceptance this replaces admitted `caller-supplied`, which the
    # shipped matrix cannot produce and which is precisely the value `init_assembly`
    # treats as "do not warn". Measured: under a mutation making both interceptors
    # report `caller-supplied`, the old form passed on its own (five sibling tests
    # caught it, so nothing shipped wrong — but this gate decided nothing).
    #
    # `discarded` and `caller-supplied` are real and reachable; they are simply not
    # reachable from *this* matrix, so each has its own case below rather than a
    # standing waiver here (AAASM-5752).
    # Per LABEL, not as a union. Review measured why the union is not enough: it
    # detects a NEW value but not a WRONG ASSIGNMENT within the set. Flipping
    # `GatewayClient.audit_sink` from `absent` to `forwarded` — a false retention
    # claim on two shipped configurations, the exact defect this type exists to
    # prevent — left the whole suite green, because {absent, forwarded} was still
    # the union. The mapping binds each branch to its own answer.
    expected = {
        "runtime reachable, enforce": AUDIT_SINK_FORWARDED,
        "runtime reachable, observe": AUDIT_SINK_FORWARDED,
        "runtime unreachable, enforce": AUDIT_SINK_ABSENT,
        "runtime unreachable, observe": AUDIT_SINK_ABSENT,
        "native missing, enforce": AUDIT_SINK_ABSENT,
        "native missing, observe": AUDIT_SINK_ABSENT,
        "langchain callback handler": AUDIT_SINK_FORWARDED,
    }
    observed = {label: getattr(handler, "audit_sink", None) for label, handler in handlers.items()}
    assert observed == expected, (
        f"the shipped handler matrix reported {observed}; it is pinned to {expected}. A changed "
        "value is either a handler that stopped declaring what it does with the hook-layer audit "
        "record, or a genuine new branch that needs its own case and its own reason "
        "(AAASM-5731, AAASM-5752)"
    )


def test_the_langchain_handler_reports_discarded_when_what_it_wraps_records_nothing() -> None:
    """`discarded` is reachable, just not from the shipped matrix above.

    The handler defines ``on_tool_end``, so the adapters' hook lookup resolves on
    it and the record is built and handed over — then stops, because the wrapped
    interceptor has nowhere to put it. That is `discarded`, and it is not
    `absent`: `absent` says nothing constructs the event, and here something does.
    """

    # Driven from the shipped factory, not from a stub. Review measured the
    # difference: with a 3-line `class RecordsNothing: audit_sink = "absent"`
    # this case still passed under a mutation setting `GatewayClient.audit_sink`
    # to `forwarded`, which removes `discarded` from two of the four shipped
    # configurations that produce it. The stub pinned the substitution rule
    # inside `AssemblyCallbackHandler`; these labels pin that shipped code
    # reaches the value at all.
    handlers = _shipped_handler_matrix([])
    for label in ("runtime unreachable, observe", "native missing, observe"):
        wrapped = AssemblyCallbackHandler(handlers[label])
        assert wrapped.audit_sink == AUDIT_SINK_DISCARDED, (
            f"the LangChain handler wrapping the '{label}' interceptor reported "
            f"{wrapped.audit_sink!r}; `_register_adapters` performs exactly this substitution"
        )


def test_a_handler_that_declares_nothing_is_reported_as_caller_supplied() -> None:
    """`caller-supplied` is the no-claim answer, and is likewise outside the matrix.

    This SDK builds no handler that reaches it — it is what a caller's own object
    resolves to. Pinned here so the value stays covered while the matrix assertion
    above stays narrow.
    """

    class Bare:
        pass

    assert AssemblyCallbackHandler(Bare()).audit_sink == AUDIT_SINK_CALLER_SUPPLIED
    assert resolve_audit_sink(Bare()) == AUDIT_SINK_CALLER_SUPPLIED


def test_resolving_a_disposition_never_raises() -> None:
    """A client whose ``__getattr__`` raises yields `absent`, not an exception.

    ``audit_sink`` became a computed property under AAASM-5731; before this, a
    wrapped client that raises on attribute access surfaced as
    ``ConfigurationError: Failed to initialize assembly runtime: client is not
    connected`` out of ``init_assembly``. Both resolvers are covered because the
    reproduction reaches the delegating one — ``RuntimeQueryInterceptor.audit_sink``
    calls it — while the other is what a caller-facing handler uses (AAASM-5752).
    """

    class Raises:
        def __getattr__(self, name: str) -> object:
            raise RuntimeError("client is not connected")

    assert resolve_audit_sink(Raises()) == AUDIT_SINK_ABSENT
    assert resolve_delegated_audit_sink(Raises()) == AUDIT_SINK_ABSENT
    # The path the reproduction actually took: through the shipped interceptor's
    # property rather than through the resolver directly.
    assert RuntimeQueryInterceptor(Raises(), None, _AGENT_ID, enforce=True).audit_sink == AUDIT_SINK_ABSENT
    # And with the raising object in the runtime-client slot, which is read first.
    assert RuntimeQueryInterceptor(Raises(), Raises(), _AGENT_ID, enforce=True).audit_sink == AUDIT_SINK_ABSENT


# Only the enforce labels: under observe with no runtime the factory returns the
# bare GatewayClient, which declares 'absent' but has no check_tool_start for the
# positive control below to stand on. That branch's declaration is covered by the
# exhaustiveness sweep instead.
@pytest.mark.parametrize("label", ["runtime unreachable, enforce"])
def test_a_handler_declaring_absent_resolves_no_audit_hook(label: str) -> None:
    """``absent`` means the hook does not resolve — not merely that it records nothing.

    The distinction is load-bearing: it is why the gap covers the ALLOWED path.
    The controls are on the same objects, so a blanket ``getattr`` failure cannot
    masquerade as the finding.

    Every label here is a run with no reachable runtime, which is what makes the
    branch real rather than the only branch: the reachable labels resolve the
    hook and declare ``forwarded``, and
    :func:`test_the_disposition_moves_with_the_runtime` compares the two.
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
    # delegation to the wrapped GatewayClient works. Without these, the
    # `is None` assertions above are consistent with a broken probe.
    assert callable(handler.check_tool_start)
    assert callable(handler.report_edge)


@pytest.mark.parametrize("label", ["runtime reachable, enforce", "runtime reachable, observe"])
def test_a_handler_declaring_forwarded_resolves_the_audit_hook(label: str) -> None:
    """The other side of the same split, on the same matrix.

    The disposition is computed from the runtime client, so a constant would pass
    every reachable case here. Pairing this with the ``absent`` cases above is
    what shows the computation moving rather than agreeing by luck.
    """
    handlers = _shipped_handler_matrix([])
    handler = handlers[label]
    assert handler.audit_sink == AUDIT_SINK_FORWARDED

    for hook in _AUDIT_HOOKS:
        assert callable(getattr(handler, hook, None)), (
            f"{label} declares {AUDIT_SINK_FORWARDED!r} but {hook!r} does not resolve on it; "
            "the adapters look the hook up by name, so an unresolved one records nothing"
        )


def test_the_disposition_moves_with_the_runtime() -> None:
    """Two constructions of the same code, not two constants compared.

    ``build_governance_interceptor`` is driven twice over inputs that differ in
    exactly one thing — whether a runtime client is present — and the two
    dispositions must differ. Without this, ``audit_sink`` could return a fixed
    literal and every case above would still be green on its own side.
    """
    reachable = _shipped_interceptor(_RecordingRuntimeClient(), [])
    unreachable = _shipped_interceptor(None, [])
    assert reachable.audit_sink == AUDIT_SINK_FORWARDED
    assert unreachable.audit_sink == AUDIT_SINK_ABSENT
    assert reachable.audit_sink != unreachable.audit_sink


@pytest.mark.parametrize("decision", ["allow", "deny"])
def test_the_shipped_path_forwards_the_record_across_the_native_boundary(
    monkeypatch: pytest.MonkeyPatch, decision: str
) -> None:
    """The load-bearing measurement, end to end and on both branches (AAASM-5750).

    It is the inversion of the assertion this suite shipped with. Nothing here
    injects a sink: the handler is the one ``build_governance_interceptor``
    returns, driven through the SDK's real governed-tool chain, and the only
    substitution is the native extension itself — which is the boundary being
    measured, not the code under test.

    Deleting the ``send_tool_outcome`` call from ``record_result`` turns both
    parametrisations red.
    """
    install_fake_core(monkeypatch, FakeRuntimeClient())
    native = _RecordingRuntimeClient(decision=decision, reason=f"policy forbids this {_PROBE_RESULT}")
    http_crossings: list[str] = []
    handler = _shipped_interceptor(native, http_crossings)
    assert handler.audit_sink == AUDIT_SINK_FORWARDED

    outcome, _value = _run_governed(handler)
    assert outcome == ("raised" if decision == "deny" else "returned")

    # Positive control: the check crossed the native boundary carrying the probe.
    # Without it an empty event list is indistinguishable from a probe that never
    # ran — and it stays a control rather than the finding because the assertion
    # below looks only at the send_event channel.
    assert any(crossing.startswith("query_policy") and _PROBE in crossing for crossing in native.crossings), (
        f"no policy query carrying the probe crossed the native boundary (crossings: "
        f"{native.crossings}); the probe never ran, so nothing below proves anything"
    )

    # The record channel specifically. On the denied branch the discriminator is
    # the deny reason rather than the tool result, because the tool never ran and
    # asserting on its output there is an assertion that cannot fail.
    sends = [crossing for crossing in native.crossings if crossing.startswith("send_event")]
    carrying = [crossing for crossing in sends if _PROBE_RESULT in crossing]
    assert carrying, (
        f"the {decision} branch sent no audit record carrying {_PROBE_RESULT!r} across the "
        f"native boundary; send_event crossings were {sends}, and the handler declares "
        f"{handler.audit_sink!r} — the declaration and the behaviour disagree"
    )

    # The record must be tagged as the outcome it describes, or a deny and an
    # allow are the same event downstream.
    expected_type = "PolicyViolation" if decision == "deny" else "ToolCallIntercepted"
    assert any(expected_type in crossing for crossing in carrying), (
        f"the {decision} branch's record is not tagged {expected_type!r}: {carrying}"
    )

    # The HTTP boundary must stay out of it: the record rides the native channel,
    # and a copy going out over the gateway's HTTP surface would be a second,
    # unaccounted path for tool output to leave the process.
    assert not [crossing for crossing in http_crossings if _PROBE_RESULT in crossing], (
        f"the record also crossed the HTTP boundary: {http_crossings}"
    )


def test_a_malformed_record_payload_is_rejected_at_the_native_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The boundary double must be able to say no, or crossing it proves little.

    The real ``GovernanceEvent`` constructor validates its argument as
    ``aa_core::AuditEntry`` JSON and raises on anything else, so a builder that
    emits the wrong shape produces no record at all. If the double accepted
    everything, the assertions above would pass over a payload the shipped
    extension rejects.
    """
    install_fake_core(monkeypatch, FakeRuntimeClient())
    from agent_assembly._core import GovernanceEvent

    with pytest.raises(ValueError):
        GovernanceEvent(json.dumps({"event_type": "ToolCallIntercepted"}))

    # And the builder's real output is accepted, so the check above is a
    # discriminator rather than a double that rejects everything.
    assert GovernanceEvent(
        build_tool_outcome_payload(
            tool_name="web_search", result=_PROBE_RESULT, agent_id=_AGENT_ID, run_id="run-1", denied=False
        )
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


def test_a_caller_supplied_recording_client_is_not_reported_as_absent() -> None:
    """A false ``absent`` is a claim about the caller's code that this SDK cannot make.

    Without a runtime, ``RuntimeQueryInterceptor`` owns no audit hook —
    ``__getattr__`` hands both names to the wrapped client — so its disposition is
    the client's. When it was a fixed class attribute, a caller-supplied client
    whose ``record_result`` resolves still reported ``absent``, contradicting the
    very hook the adapters would have called, and the LangChain handler on top
    compounded it to ``discarded``.

    The direction of the old error matters and is why this is a correctness fix
    rather than a severity one: it under-claimed. It never reported retention
    where there was none.
    """
    http_crossings: list[str] = []

    class _RecordingClient(GatewayClient):
        def record_result(self, **_kwargs: Any) -> None:
            return None

    client = _RecordingClient(_GW_URL, _AGENT_ID, api_key=_API_KEY)
    client._client = httpx.Client(base_url=client.gateway_url, transport=_RecordingTransport(http_crossings))
    # No runtime client: the SDK contributes no sink of its own here, so what the
    # adapters would find is the caller's hook and nothing else. With a runtime
    # the SDK's own sink resolves first and the answer is 'forwarded', which is a
    # claim about this SDK rather than about the caller's client.
    interceptor = build_governance_interceptor(client, _AGENT_ID, None, runtime_client=None, native_available=True)

    # Precondition: the hook really does resolve through the delegation, or this
    # test is asserting about a situation that cannot arise.
    assert callable(getattr(interceptor, "record_result", None))

    assert resolve_audit_sink(interceptor) == AUDIT_SINK_CALLER_SUPPLIED
    assert resolve_audit_sink(AssemblyCallbackHandler(interceptor)) == AUDIT_SINK_CALLER_SUPPLIED

    # Control on the same shapes: an interceptor with no runtime still reads
    # 'absent', so the caller-supplied answer above is a discrimination rather
    # than a blanket one.
    shipped = _shipped_interceptor(None, http_crossings)
    assert resolve_audit_sink(shipped) == AUDIT_SINK_ABSENT
    assert resolve_audit_sink(AssemblyCallbackHandler(shipped)) == AUDIT_SINK_DISCARDED


def test_the_langchain_handler_forwards_or_drops_with_its_interceptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The LangChain callback path is a second, separate hop the record must survive.

    The handler defines ``on_tool_end``, so the adapters' lookup resolves on it —
    and it then forwards to the *interceptor's* ``on_tool_end`` by that name
    specifically, not by the ``record_result``-first order every other adapter
    uses. Until AAASM-5750 no interceptor had one, so the record was accepted here
    and dropped one hop later: ``discarded``, not ``absent``.

    Both directions are driven, because the handler's disposition is its
    interceptor's and a single direction cannot show that.
    """
    install_fake_core(monkeypatch, FakeRuntimeClient())
    native = _RecordingRuntimeClient()
    http_crossings: list[str] = []
    forwarding = AssemblyCallbackHandler(_shipped_interceptor(native, http_crossings))

    assert forwarding.audit_sink == AUDIT_SINK_FORWARDED
    assert callable(forwarding.on_tool_end)
    forwarding.on_tool_end(_PROBE_RESULT, run_id=uuid.uuid4())
    assert any(crossing.startswith("send_event") and _PROBE_RESULT in crossing for crossing in native.crossings), (
        f"the LangChain callback path sent no record carrying the probe: {native.crossings}"
    )

    # The other direction, on the same class: with no runtime under it the hop
    # still ends here, and the handler must say 'discarded' rather than 'absent'
    # — something did construct and accept the record.
    dropping_native = _RecordingRuntimeClient()
    dropping = AssemblyCallbackHandler(_shipped_interceptor(None, []))
    assert dropping.audit_sink == AUDIT_SINK_DISCARDED
    dropping.on_tool_end(_PROBE_RESULT, run_id=uuid.uuid4())
    assert not [c for c in dropping_native.crossings if _PROBE_RESULT in c]


def _init_sdk_only(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(
        core_assembly,
        "_start_network_layer",
        lambda **_kwargs: ("sdk-only", core_assembly._noop_shutdown),
    )
    core_assembly._ACTIVE_CONTEXT = None
    return init_assembly(gateway_url=_GW_URL, api_key=_API_KEY, agent_id=_AGENT_ID, mode="sdk-only")


def test_init_assembly_warns_about_the_audit_gap_only_when_there_is_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The signal must arrive with nothing opted into — and only when it is true.

    A caller who has to already suspect the problem in order to discover it has
    not been told. A caller warned on every run, including the ones whose records
    do reach the runtime, stops reading the warning — which costs the real case
    its signal too. So both directions are driven through the same ``init_assembly``.
    """
    # No runtime: connect_runtime_client returns None, so no hook resolves.
    monkeypatch.setattr(core_assembly, "connect_runtime_client", lambda _agent_id: None)
    context = _init_sdk_only(monkeypatch)
    try:
        stderr = capsys.readouterr().err
        assert context.audit_sink == AUDIT_SINK_ABSENT
        for expected in ("audit", "NOT retained", context.audit_sink, "ALLOWED", "AAASM-5731"):
            assert expected in stderr, f"{expected!r} missing from init stderr: {stderr!r}"
    finally:
        context.shutdown()
        core_assembly._ACTIVE_CONTEXT = None


def test_init_assembly_stays_quiet_when_the_record_is_forwarded(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other arm of the warning, through the same ``init_assembly``.

    Without it the assertions in the test above are satisfied by a build that
    warns unconditionally — which is what the condition at the call site used to
    do, and what made the warning worth nothing on the run that has no gap.
    """
    install_fake_core(monkeypatch, FakeRuntimeClient(decision="allow"))
    context = _init_sdk_only(monkeypatch)
    try:
        stderr = capsys.readouterr().err
        assert context.audit_sink == AUDIT_SINK_FORWARDED
        assert "NOT retained" not in stderr, (
            f"init warned that records are not retained on a run that forwards them: {stderr!r}"
        )
    finally:
        context.shutdown()
        core_assembly._ACTIVE_CONTEXT = None


def test_building_an_interceptor_over_a_raising_client_reports_absent_rather_than_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reachable form of the AAASM-5752 symptom, at the shipped factory.

    The ticket is explicit that this is "unreachable on the shipped path —
    ``init_assembly`` builds its own ``GatewayClient`` — and reachable only by
    calling ``build_governance_interceptor`` directly with such a client". That
    is measured, not assumed: an ``init_assembly``-level version of this test was
    written first and *passed with every guard reverted*, because a client that
    raises degrades the connect itself, so init reports ``absent`` for an
    unrelated reason. It was dropped rather than shipped as a tautology.

    So the binding is made where the defect actually lives. Reverting any of the
    three guards reddens this.
    """

    class RaisesOnEveryLookup:
        def __getattr__(self, name: str) -> Any:
            raise RuntimeError("client is not connected")

    interceptor = build_governance_interceptor(
        RaisesOnEveryLookup(),
        _AGENT_ID,
        None,
        runtime_client=RaisesOnEveryLookup(),
        native_available=True,
    )
    assert interceptor.audit_sink == AUDIT_SINK_ABSENT
