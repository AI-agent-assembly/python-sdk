"""Unit tests for the lazy `__getattr__` re-exports on `agent_assembly.core`.

`agent_assembly.core` resolves its public symbols lazily (PEP 562) so importing
the package does not eagerly pull in `core.assembly`'s dependency surface. These
tests exercise each lazy branch and the unknown-attribute guard.
"""

from __future__ import annotations

import pytest

import agent_assembly.core as core


def test_lazy_getattr_resolves_init_assembly_and_assembly_context() -> None:
    from agent_assembly.core.assembly import AssemblyContext, init_assembly

    assert core.init_assembly is init_assembly
    assert core.AssemblyContext is AssemblyContext


def test_lazy_getattr_resolves_lineage_registry() -> None:
    from agent_assembly.core.lineage import LineageRegistry

    assert core.LineageRegistry is LineageRegistry


def test_lazy_getattr_raises_attribute_error_for_unknown_symbol() -> None:
    missing_name = "does_not_exist"
    with pytest.raises(AttributeError, match="has no attribute 'does_not_exist'"):
        getattr(core, missing_name)  # exercises the __getattr__ unknown-symbol guard


def test_all_lists_the_public_lazy_exports() -> None:
    assert set(core.__all__) == {"init_assembly", "AssemblyContext", "LineageRegistry"}
