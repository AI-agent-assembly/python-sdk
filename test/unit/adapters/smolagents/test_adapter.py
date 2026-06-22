"""Unit tests for the smolagents adapter contract and lifecycle."""

from __future__ import annotations

from typing import Any

from agent_assembly.adapters.smolagents.adapter import SmolagentsAdapter


def test_framework_name_is_smolagents() -> None:
    assert SmolagentsAdapter().get_framework_name() == "smolagents"


def test_supported_versions_are_non_empty() -> None:
    versions = SmolagentsAdapter().get_supported_versions()
    assert versions
    assert all(v.strip() for v in versions)


def test_validate_registration_passes_contract() -> None:
    # Must not raise — name and version ranges satisfy the base contract.
    SmolagentsAdapter().validate_registration()


def test_register_and_unregister_are_idempotent() -> None:
    class _Interceptor:
        _enforce = True

        def check_tool_start(self, **kwargs: Any) -> dict[str, str]:
            del kwargs
            return {"status": "allow"}

    adapter = SmolagentsAdapter()
    # register() validates the contract then installs hooks; with smolagents
    # absent in a pure unit run, apply() returns False but registration succeeds.
    adapter.register(_Interceptor())
    adapter.unregister_hooks()
    # Double-unregister must be safe.
    adapter.unregister_hooks()
