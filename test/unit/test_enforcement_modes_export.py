"""AAASM-4856: `agent_assembly.ENFORCEMENT_MODES` public parity surface.

The cross-SDK enforcement-mode parity conformance cross-check in e2e-public
reads ``getattr(agent_assembly, "ENFORCEMENT_MODES", None)`` to assert the
installed Python SDK against the canonical ordered set. These tests pin that
surface: it must resolve, be publicly discoverable via ``__all__``, carry the
exact canonical order, and stay in sync with the private membership validator
it is the single source of truth for.
"""

from __future__ import annotations

import agent_assembly
import agent_assembly.core.assembly as assembly


def test_enforcement_modes_is_the_canonical_ordered_tuple() -> None:
    # Order is significant — the cross-SDK cross-check compares sequences.
    assert agent_assembly.ENFORCEMENT_MODES == ("enforce", "observe", "disabled")


def test_enforcement_modes_is_a_public_export() -> None:
    assert "ENFORCEMENT_MODES" in agent_assembly.__all__


def test_enforcement_modes_stays_in_sync_with_private_validator() -> None:
    # The public constant is the single source of truth; the private validator
    # is derived from it, so the two can never drift.
    assert frozenset(agent_assembly.ENFORCEMENT_MODES) == assembly._VALID_ENFORCEMENT_MODES
