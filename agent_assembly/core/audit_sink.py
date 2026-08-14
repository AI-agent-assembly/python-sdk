"""What the SDK's own governance handlers do with hook-layer audit records.

The framework adapters offer the outcome of every governed tool call — allowed
or denied — to an audit hook on the interceptor they were handed
(``record_result``, falling back to ``on_tool_end``). Both hooks are duck-typed
and both return ``None``, so a handler that retains the record and one that does
nothing with it are indistinguishable at the call site.

``RuntimeQueryInterceptor`` defines ``record_result``, which forwards the record
to the runtime over the native event channel (AAASM-5750). Until that landed
neither hook resolved at all on any interceptor this SDK ships — the ``getattr``
guard found nothing and returned without emitting, for **allowed** calls as much
as denied ones.

Which of the two a given run is in still depends on the run, so the declaration
is not decoration. An interceptor built without a native runtime — the
fail-closed one, or a build with no extension — has no channel to send on and
still resolves no hook. This module is how the difference stops being invisible:
every handler the SDK ships declares its disposition; :func:`resolve_audit_sink`
reads it; ``init_assembly`` warns about it and reports it on the returned
context.

The ADR 0033 §6 term follows the disposition rather than the SDK as a whole:

* :data:`AUDIT_SINK_FORWARDED` — the event reaches the runtime's evidence
  pipeline, which is what *Observed* asks for.
* :data:`AUDIT_SINK_ABSENT` — the control is configured and its channel is
  unavailable, which is *Degraded*; deliberately not *Unmeasured*, since §6
  reserves that for an action no control inspected, and here exactly where the
  record stops has been measured against the native boundary.
* :data:`AUDIT_SINK_DISCARDED` — a hook resolves and drops the record, so no
  evidence exists on that path either.
"""

from __future__ import annotations

from typing import Any, Literal, get_args

type AuditSinkDisposition = Literal["forwarded", "absent", "discarded", "caller-supplied"]
"""What a governance handler does with the hook-layer audit record.

The vocabulary separates *how* a record fails to survive, not merely that it
does, because the two failures have different blast radii and different remedies
— and the three SDKs sit on both sides of the split, so collapsing them would
misdescribe at least one of them.
"""

AUDIT_SINK_FORWARDED: AuditSinkDisposition = "forwarded"
"""An audit hook resolves and hands the record to the runtime.

The record crosses the native event channel — the same
``RuntimeClient.send_event`` primitive and the same connected session the agent
registration already uses — into the runtime's audit pipeline, on the allowed
path and the denied one alike.

It says "forwarded", not "recorded", on purpose. This SDK can observe that the
event crossed the boundary; what the runtime and the gateway behind it retain is
theirs to state. Delivery is also best-effort: the channel is fire-and-forget, so
a failed send degrades to no record rather than to a failed tool call.
"""

AUDIT_SINK_ABSENT: AuditSinkDisposition = "absent"
"""No audit hook resolves on this handler, so no record is even attempted.

This is what an interceptor built without a reachable native runtime does — the
fail-closed one, and any build with no extension. It is strictly worse than
``"discarded"``: nothing constructs the event, so supplying a sink downstream is
not sufficient on its own — the call site finds no hook to call. It is also why
the gap covers the **allowed** path and not only the denied one.
"""

AUDIT_SINK_DISCARDED: AuditSinkDisposition = "discarded"
"""An audit hook resolves, accepts the record, and drops it.

The call site is correct and the sink is not. This is what the LangChain
:class:`~agent_assembly.adapters.langchain.callback_handler.AssemblyCallbackHandler`
does when the interceptor it wraps has no ``on_tool_end`` to forward to, and it
is what the Go and Node SDKs' shipped clients do (AAASM-5731 / AAASM-5681).
"""

AUDIT_SINK_CALLER_SUPPLIED: AuditSinkDisposition = "caller-supplied"
"""The handler did not come from this SDK, so this SDK claims nothing about it.

The **absence of a claim, not an assurance** that the record is retained.
Whichever §6 term the caller's own handler earns is the caller's to establish,
not this SDK's to assert.
"""

AUDIT_HOOK_NAMES = ("record_result", "on_tool_end")
"""The audit hooks the adapters look up, in the order they look them up.

Defined here so the interceptors, the tests and the adapters cannot drift apart
on what counts as "the audit hook" — a drift that would make every
:data:`AUDIT_SINK_ABSENT` declaration below unfalsifiable.
"""

AUDIT_SINK_ATTRIBUTE = "audit_sink"
"""Attribute name a handler declares its disposition under.

Duck-typed for the same reason the audit hook itself is: the adapters accept any
object as a ``callback_handler``, so requiring a base class or a Protocol
registration would break every caller-supplied handler that works today.
"""

_VALID_DISPOSITIONS = frozenset(get_args(AuditSinkDisposition.__value__))


def resolve_delegated_audit_sink(delegate: Any) -> AuditSinkDisposition:
    """Disposition of an interceptor that delegates its audit hooks to ``delegate``.

    Computed rather than fixed, because it genuinely depends on what is wrapped.
    Review of AAASM-5731's PR measured the cost of hard-coding it: with a
    caller-supplied client whose ``record_result`` resolves,
    ``RuntimeQueryInterceptor`` still reported :data:`AUDIT_SINK_ABSENT` — a false
    ``absent``, contradicting the very hook the adapters would have called.

    Two branches, both honest:

    * no hook resolves on ``delegate`` — nothing can be attempted through this
      interceptor either, so :data:`AUDIT_SINK_ABSENT`;
    * a hook resolves — this SDK builds no *client* that has one (the sink lives
      on the interceptor, not on the wrapped client), so the hook came from the
      caller and this SDK makes no claim about it:
      :data:`AUDIT_SINK_CALLER_SUPPLIED`.

    Note the failure direction if this is ever wrong: it under-claims. Reporting
    ``caller-supplied`` where a record is in fact dropped withholds a claim; the
    reverse — reporting retention where there is none — is the defect this whole
    type exists to prevent, and this function cannot produce it.
    """
    if any(callable(getattr(delegate, hook, None)) for hook in AUDIT_HOOK_NAMES):
        return AUDIT_SINK_CALLER_SUPPLIED
    return AUDIT_SINK_ABSENT


def resolve_audit_sink(handler: Any) -> AuditSinkDisposition:
    """Report what ``handler`` does with the hook-layer audit record.

    A handler that declares nothing — or declares something outside the
    vocabulary — is reported as :data:`AUDIT_SINK_CALLER_SUPPLIED`. An
    unrecognised value is deliberately *not* trusted through: a typo must degrade
    to "this SDK makes no claim", never to a claim this SDK cannot stand behind.

    ``None`` is :data:`AUDIT_SINK_ABSENT` rather than caller-supplied: no handler
    means no hook to call, which is the same thing the shipped interceptors do.
    """
    if handler is None:
        return AUDIT_SINK_ABSENT
    declared = getattr(handler, AUDIT_SINK_ATTRIBUTE, None)
    if isinstance(declared, str) and declared in _VALID_DISPOSITIONS:
        # Cast is safe: membership in _VALID_DISPOSITIONS is exactly the Literal.
        return declared  # type: ignore[return-value]
    return AUDIT_SINK_CALLER_SUPPLIED
