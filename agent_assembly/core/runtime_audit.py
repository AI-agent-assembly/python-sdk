"""Hand a governed tool call's outcome to the runtime's event channel.

The framework adapters build an audit record for every governed call — allowed
or denied — and offer it to an audit hook on the interceptor they were handed.
Until AAASM-5750 no interceptor this SDK ships had one, so the record was built
and never emitted. This module is the sink that closes that: it encodes the
outcome and hands it to the native ``RuntimeClient.send_event``, the same
primitive and the same connected session that ``register_agent`` already uses.

**What the SDK can and cannot say about the result.** ``send_event`` is
fire-and-forget over a bounded IPC channel: it hands the event to the runtime and
returns, with no acknowledgement. **That handoff is the entire claim, and it is
not ADR 0033 §6 *Observed*.** §6 requires a durable event attributed to the
action; nothing observable from this side establishes one, so this module must
not be cited as evidence that a governed call was recorded. Retention past the
boundary belongs to the runtime and the gateway behind it, and asserting their
outcome from here would broaden a claim this layer cannot see (ADR 0034).

**The identity fields are placeholders, not attribution.** The native
``GovernanceEvent`` constructor validates its argument as ``aa_core::AuditEntry``
JSON, so the payload has to carry that struct's shape — including ``agent_id``,
``session_id`` and the two chain hashes. Only ``event_type`` is read from it (to
tag the event) and the JSON as a whole travels as an opaque ``details`` label;
none of those four fields reaches the wire as an identity or a chain link. They
are zero-filled rather than fabricated, and the agent identity the SDK actually
knows travels inside ``payload`` where it is plainly a claim by the SDK. The
authoritative attribution is the runtime's, derived from the verified identity
of the IPC connection the event arrived on — not from anything written here.
"""

from __future__ import annotations

import json
import time
from typing import Any, Final

#: Zero-filled stand-ins for the `AuditEntry` fields the wire does not read.
#: See the module docstring: writing a plausible-looking value into an identity
#: or hash-chain field that nothing downstream honours is how a placeholder gets
#: mistaken for evidence later.
_UNSET_ID: Final = [0] * 16
_UNSET_HASH: Final = [0] * 32

#: `aa_core::AuditEventType` variants for the two outcomes the adapters report.
#: A denied call is a policy violation, not an intercepted call that ran.
#:
#: **The tag does not currently reach anything that acts on it.** An earlier
#: version of this comment said the runtime "keys its own handling off this tag";
#: it does not — it keys off ``action_type`` / ``detail``, and
#: ``aa_sdk_client::report_event`` puts this tag into proto ``labels`` while
#: leaving ``action_type``, ``detail`` and ``decision`` at their proto3 zero. So
#: the runtime's ``is_policy_violation`` is false for every hook-layer record and
#: a deny is batched exactly like an allow. The distinction is preserved here
#: because collapsing it would be wrong at the source too, but it is carried, not
#: honoured — do not build a claim on it.
_EVENT_TYPE_ALLOWED: Final = "ToolCallIntercepted"
_EVENT_TYPE_DENIED: Final = "PolicyViolation"


def build_tool_outcome_payload(
    *,
    tool_name: str,
    result: Any,
    agent_id: str | None,
    run_id: str | None,
    denied: bool,
) -> str:
    """Encode one governed call's outcome as ``aa_core::AuditEntry`` JSON.

    ``result`` carries the tool's output on the allowed path and the
    short-circuit error text on the denied one, so it is written under a
    different key per branch: a reader must not have to infer from an empty
    string whether a tool returned nothing or never ran.

    ``seq`` is 0 because sequencing is the runtime's — it assigns one per
    connection on ingress, and a number chosen here would be a second, competing
    ordering that agrees with nothing.
    """
    outcome_key = "error" if denied else "result"
    payload = {
        "agent_id": agent_id or "",
        "tool_name": tool_name,
        "run_id": run_id or "",
        "denied": denied,
        outcome_key: "" if result is None else str(result),
    }
    return json.dumps(
        {
            "seq": 0,
            "timestamp_ns": time.time_ns(),
            "event_type": _EVENT_TYPE_DENIED if denied else _EVENT_TYPE_ALLOWED,
            "agent_id": _UNSET_ID,
            "session_id": _UNSET_ID,
            "payload": json.dumps(payload),
            "previous_hash": _UNSET_HASH,
            "entry_hash": _UNSET_HASH,
        }
    )


def runtime_can_record(runtime_client: Any) -> bool:
    """Whether ``runtime_client`` exposes the native event channel.

    Read rather than assumed so the disposition an interceptor declares is
    computed from the same fact :func:`send_tool_outcome` acts on. A build whose
    native shim predates ``send_event``, or a caller-supplied stand-in that only
    answers policy queries, must declare that it records nothing rather than
    claim a channel it does not hold.
    """
    return callable(getattr(runtime_client, "send_event", None))


def send_tool_outcome(
    runtime_client: Any,
    *,
    tool_name: str,
    result: Any,
    agent_id: str | None,
    run_id: str | None,
    denied: bool,
) -> bool:
    """Send one governed call's outcome to the runtime. Returns whether it went.

    **Every failure is swallowed.** The adapters call the audit hook from inside
    the governed tool path — on the allowed branch without a guard of their own
    (``adapters/_shared/tool_governance.py``) — so an exception raised here would
    surface as a failure of the tool call itself. A degraded audit channel must
    never change what a governed call does, in either direction: it must not fail
    an allowed call, and it must not turn a deny into some other error.

    The boolean is returned rather than logged so a caller (and a test) can tell
    a send that happened from one that did not, without this function acquiring
    an opinion about how to report it.
    """
    if not runtime_can_record(runtime_client):
        return False

    try:
        from agent_assembly._core import GovernanceEvent
    except ImportError:
        # The interceptor that owns this sink only exists over a connected native
        # runtime, so this is unreachable on the shipped path — but a partially
        # built extension must degrade to "no record", not to an ImportError
        # escaping a tool call.
        return False

    try:
        event = GovernanceEvent(
            build_tool_outcome_payload(
                tool_name=tool_name,
                result=result,
                agent_id=agent_id,
                run_id=run_id,
                denied=denied,
            )
        )
        runtime_client.send_event(event)
    except Exception:
        return False
    return True
