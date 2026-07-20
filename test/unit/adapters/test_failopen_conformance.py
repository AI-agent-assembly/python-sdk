"""Fail-open conformance matrix: every governing adapter × fault scenario × mode.

This suite is the systemic fix (AAASM-4800) that ends the per-round fail-open
whack-a-mole. Rather than one bespoke regression test per adapter caught failing
open — openai_agents (AAASM-4734 → AAASM-4782), langchain (AAASM-4790) — it drives
*every* adapter that has a pre-execution tool gate through the *same* fault
scenarios under the *same* enforcement postures and asserts one invariant:

    Under an enforce posture (explicit ``enforce`` and the ``None``/omitted default),
    a governance fault or deny MUST block the tool. Fail-open is only permitted under
    the explicit dry-run postures (``observe`` / ``disabled``).

Two guards make this hard to regress:

* The parametrized matrix (:func:`test_failopen_conformance`) covers the exact
  cells that previously regressed — see the ``test_regression_*`` guards below for
  the named ticket ties.
* The completeness check (:func:`test_every_adapter_has_a_driver`) fails if a new or
  regressed adapter package ships without a driver or a justified exemption, so an
  ungoverned adapter cannot merge unnoticed.

The harness, registry, and fake interceptors live in
``test.unit.adapters.failopen_conformance``.
"""

from __future__ import annotations

from test.unit.adapters import failopen_conformance as conf

import pytest

from agent_assembly.core.runtime_interceptor import _local_posture_is_enforce


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_name", sorted(conf.DRIVERS))
@pytest.mark.parametrize("scenario", conf.SCENARIOS)
@pytest.mark.parametrize("mode_id,mode_value", conf.MODES, ids=[m[0] for m in conf.MODES])
async def test_failopen_conformance(
    adapter_name: str,
    scenario: str,
    mode_id: str,
    mode_value: str | None,
) -> None:
    """No governing adapter fails open under enforce; all pin the dry-run postures.

    ``mode_id`` names the posture for readable parametrize ids; ``mode_value`` is the
    ``enforcement_mode`` fed to the real posture resolver.
    """
    is_enforce = _local_posture_is_enforce(mode_value)
    ran = await conf.run_scenario(adapter_name, scenario, mode_value)
    want = conf.expected_run(scenario, is_enforce=is_enforce)

    posture = "enforce" if is_enforce else "fail-open"
    verb = "run" if want else "be blocked"
    assert ran is want, (
        f"{adapter_name} under {mode_id} ({posture}) on {scenario}: tool expected to {verb}, but ran={ran}"
    )


def test_every_adapter_has_a_driver() -> None:
    """A new/regressed adapter package cannot ship ungoverned (the anti-whack-a-mole guard).

    Every adapter package on disk must be either a governed adapter with a registered
    driver or an explicitly justified exemption. Symmetrically, no driver/exemption may
    reference a package that no longer exists.
    """
    on_disk = conf.discover_adapter_packages()
    covered = set(conf.DRIVERS) | set(conf.EXEMPT_ADAPTERS)

    ungoverned = on_disk - covered
    assert not ungoverned, (
        "adapter package(s) with no fail-open conformance driver and no exemption: "
        f"{sorted(ungoverned)}. Add a driver to failopen_conformance.DRIVERS, or an "
        "exemption with a reason to EXEMPT_ADAPTERS."
    )

    stale = covered - on_disk
    assert not stale, f"DRIVERS/EXEMPT_ADAPTERS reference package(s) not on disk: {sorted(stale)}"


def test_registry_and_exemptions_are_disjoint() -> None:
    """An adapter is either driven or exempt — never both (keeps the guard unambiguous)."""
    overlap = set(conf.DRIVERS) & set(conf.EXEMPT_ADAPTERS)
    assert not overlap, f"adapter(s) both driven and exempt: {sorted(overlap)}"


# --- Named regression guards ----------------------------------------------
#
# These duplicate specific matrix cells on purpose: they tie the fixed bugs to their
# tickets so a reviewer (and `git blame`) can see exactly which regression each pins.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    [
        conf.GATEWAY_UNREACHABLE,
        conf.GOVERNANCE_ERROR,
        conf.PENDING_FAULT,
        conf.DENY_AUDIT_RAISES,
    ],
)
async def test_regression_openai_agents_no_fail_open_under_enforce_4782(scenario: str) -> None:
    """AAASM-4782/4734: openai_agents must not run the tool on S1/S2/S5/S6 under enforce."""
    ran = await conf.run_scenario("openai_agents", scenario, "enforce")
    assert ran is False, f"openai_agents ran the tool under enforce on {scenario} (AAASM-4782 regression)"


@pytest.mark.asyncio
async def test_regression_openai_agents_deny_audit_raise_holds_under_observe_4782() -> None:
    """AAASM-4782: a deny whose audit sink raises must not downgrade to an allow, even under observe.

    This is the cell that catches the specific bug: with the audit guard removed the
    raising record re-enters the run path and the tool executes under the fail-open
    posture. The deny is authoritative, so it must block in every posture.
    """
    ran = await conf.run_scenario("openai_agents", conf.DENY_AUDIT_RAISES, "observe")
    assert ran is False, "openai_agents downgraded a deny to allow when the deny-audit raised (AAASM-4782)"


@pytest.mark.asyncio
async def test_regression_openai_agents_raising_check_denies_under_enforce_4782() -> None:
    """AAASM-4782: a governance check that RAISES must fail closed under enforce, open under observe.

    Distinct from the return-based faults in the matrix: this exercises the wrapper's
    governance-error except-handler directly.
    """
    from agent_assembly.exceptions import GatewayError

    class _RaisingCheckInterceptor:
        def __init__(self, *, enforce: bool) -> None:
            self._enforce = enforce

        def check_tool_start(self, **_kwargs: object) -> object:
            raise GatewayError("runtime query failed")

        def record_result(self, **_kwargs: object) -> None:
            return None

        def on_tool_end(self, **_kwargs: object) -> None:
            return None

    import contextlib

    from agent_assembly.exceptions import AssemblyError

    async def _drive(enforce: bool) -> bool:
        ran = [False]
        with contextlib.suppress(AssemblyError):
            await conf.DRIVERS["openai_agents"](_RaisingCheckInterceptor(enforce=enforce), ran)
        return ran[0]

    assert await _drive(enforce=True) is False, "openai_agents ran the tool when the check raised under enforce"
    assert await _drive(enforce=False) is True, "openai_agents failed closed under observe (should fail open)"


@pytest.mark.asyncio
async def test_regression_langchain_missing_check_method_denies_under_enforce_4790() -> None:
    """AAASM-4790: langchain on_tool_start must fail closed when the interceptor has no check method."""
    blocked = await conf.run_scenario("langchain", conf.MISSING_CHECK_METHOD, "enforce")
    assert blocked is False, "langchain failed open on a missing check_tool_start under enforce (AAASM-4790)"

    allowed = await conf.run_scenario("langchain", conf.MISSING_CHECK_METHOD, "observe")
    assert allowed is True, "langchain failed closed on a missing check_tool_start under observe (should fail open)"
