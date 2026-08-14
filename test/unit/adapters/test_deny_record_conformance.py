"""Every governing adapter builds an audit record on its own deny branch (AAASM-5787).

Before this, eight of the eleven governing adapters returned or raised at
``if status != "allow":`` and never reached their record helper, so a denied tool
call constructed nothing — whatever sink the interceptor had was irrelevant,
because there was no record to carry. AAASM-5750 wired the sink; this is the
half upstream of it.

Why this file rather than eight per-adapter tests
-------------------------------------------------
It reuses :mod:`test.unit.adapters.failopen_conformance`, whose drivers already
invoke each adapter's *real* governance wrapper against a fake framework tool.
Two consequences matter:

* Each parametrised case reaches **that adapter's own** deny branch. Deleting one
  adapter's record call reddens that adapter's case and no other, which is what
  makes the matrix a per-adapter control rather than one control standing in for
  eleven.
* The registry's completeness check (``test_every_adapter_has_a_driver``) already
  fails when a new adapter package ships without a driver, so a twelfth adapter
  cannot arrive un-measured here either.

What is asserted, and against what control
------------------------------------------
An offer to the audit hook is not evidence: over a connected runtime the SDK's
interceptor writes it to the native event channel unacknowledged, and
AAASM-5783 is open on ``report_event`` payloads reaching neither the live stream
nor the durable entry. So no ADR 0033 §6 *Observed* claim is made here or
anywhere downstream of it. What is asserted is narrower and checkable: the deny
branch **built** a record and handed it over.

The denied and allowed paths are compared rather than the denied one being read
alone. Both populate the hook, so "a record exists" cannot distinguish them; the
``denied`` flag can, and the allowed case is asserted to carry no such flag. A
single-sided assertion here would pass against an adapter that recorded the
allowed path twice.
"""

from __future__ import annotations

import contextlib
from test.unit.adapters import failopen_conformance as conf

import pytest


def _denied_records(records: list[dict[str, object]]) -> list[dict[str, object]]:
    return [record for record in records if record.get("denied") is True]


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_name", sorted(conf.DRIVERS))
async def test_a_policy_deny_builds_a_record_in_that_adapters_own_branch(adapter_name: str) -> None:
    """An authoritative deny hands a record to the audit hook, marked as a deny."""
    ran, records = await conf.run_scenario_capturing_records(adapter_name, conf.EXPLICIT_DENY, "enforce")

    assert ran is False, f"{adapter_name}: the tool ran under an authoritative deny"
    assert records, (
        f"{adapter_name}: the deny branch handed nothing to the audit hook, so no record "
        f"existed for any sink to carry (AAASM-5787)"
    )
    denied = _denied_records(records)
    assert denied, (
        f"{adapter_name}: {len(records)} record(s) reached the hook on the denied path but none "
        f"carried denied=True, so a reader cannot tell them from a tool that ran and returned "
        f"the denial text"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_name", sorted(conf.DRIVERS))
async def test_an_allowed_call_records_without_the_denial_flag(adapter_name: str) -> None:
    """The control that moves with the variable under test.

    Both paths reach the hook, so the presence of a record decides nothing on its
    own. This pins the other side: an allowed call records, and its record is not
    marked as a deny. Without it, an adapter that recorded the allowed outcome on
    both branches would satisfy the deny test above.
    """
    ran, records = await conf.run_scenario_capturing_records(adapter_name, conf.EXPLICIT_ALLOW, "enforce")

    assert ran is True, f"{adapter_name}: the tool did not run under an authoritative allow"
    assert records, f"{adapter_name}: the allowed path handed nothing to the audit hook"
    assert not _denied_records(records), (
        f"{adapter_name}: an allowed call produced a record marked denied=True, so the flag "
        f"does not distinguish the two paths"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_name", sorted(conf.DRIVERS))
async def test_a_deny_whose_audit_hook_raises_still_records_and_still_blocks(adapter_name: str) -> None:
    """AAASM-4782's invariant, extended to the branches AAASM-5787 added.

    The record calls are new on eight deny branches, and the hook is duck-typed
    from caller-supplied code. A raising hook must not re-enter the run path and
    downgrade a decided deny — and the offer must still have been made, which is
    why the fake captures before it raises.
    """
    ran, records = await conf.run_scenario_capturing_records(adapter_name, conf.DENY_AUDIT_RAISES, "enforce")

    assert ran is False, f"{adapter_name}: a raising audit hook let the denied tool run"
    assert _denied_records(records), f"{adapter_name}: the deny record was not offered before the hook raised"


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_name", sorted(conf.DRIVERS))
async def test_a_hook_written_to_the_allowed_path_contract_still_gets_the_deny_record(
    adapter_name: str,
) -> None:
    """The deny record must not require a wider signature than the allowed one.

    Several adapters call the audit hook with just ``tool_name`` and ``result``
    on the allowed path, so a caller-supplied handler is entitled to accept only
    those. Offering the extra keywords unconditionally raised ``TypeError``,
    which :mod:`agent_assembly.adapters._shared.audit_record` then suppressed —
    the deny recorded nothing, silently, in exactly the population the
    "eleven adapters record on deny" claim is about.

    The handler here is deliberately narrow: no ``**kwargs``, no ``denied``. It
    therefore also pins the other half — that a hook which cannot receive the
    denial marker still receives the record.
    """
    records: list[tuple[str, str]] = []

    class NarrowHandler:
        _enforce = True

        def check_tool_start(self, **_kwargs: object) -> dict[str, str]:
            return {"status": "deny", "reason": "denied by policy"}

        def wait_for_tool_approval(self, **_kwargs: object) -> dict[str, str]:
            return {"status": "deny", "reason": "denied by policy"}

        def record_result(self, *, tool_name: str, result: str) -> None:
            records.append((tool_name, result))

    from agent_assembly.exceptions import AssemblyError

    ran = [False]
    with contextlib.suppress(AssemblyError):
        await conf.DRIVERS[adapter_name](NarrowHandler(), ran)

    assert ran[0] is False, f"{adapter_name}: the tool ran under an authoritative deny"
    assert records, (
        f"{adapter_name}: a handler accepting only (tool_name, result) — the allowed-path "
        f"contract — received no deny record; the wider call raised TypeError and it was "
        f"suppressed (AAASM-5787)"
    )
