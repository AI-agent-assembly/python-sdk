"""Reusable fakes for the native ``agent_assembly._core`` extension.

These let the SDK wiring tests (AAASM-3402) exercise the native register /
query_policy path without a built extension or a running ``aa-runtime``: the
``FakeRuntimeClient`` records ``register`` calls and returns a canned
``query_policy`` decision, and ``install_fake_core`` swaps a module exposing a
``RuntimeClient`` whose ``connect`` yields one into ``sys.modules``.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest


class FakeRuntimeClient:
    """Stand-in for the native ``RuntimeClient`` (register + query_policy)."""

    def __init__(self, decision: str = "allow", reason: str = "") -> None:
        self._decision = decision
        self._reason = reason
        self.register_calls: list[tuple[str, str, str, str | None, str | None, str | None]] = []
        self.query_calls: list[tuple[Any, ...]] = []
        self.register_should_raise: Exception | None = None

    def register(
        self,
        agent_id: str,
        name: str,
        framework: str,
        gateway_endpoint: str | None = None,
        team_id: str | None = None,
        parent_agent_id: str | None = None,
    ) -> str:
        if self.register_should_raise is not None:
            raise self.register_should_raise
        self.register_calls.append((agent_id, name, framework, gateway_endpoint, team_id, parent_agent_id))
        return "policy-id-001"

    def query_policy(
        self,
        agent_id: str,
        action_type: str,
        tool_name: str | None = None,
        tool_args_json: str | None = None,
    ) -> dict[str, str]:
        self.query_calls.append((agent_id, action_type, tool_name, tool_args_json))
        return {"decision": self._decision, "reason": self._reason}

    def close(self) -> None:
        return None


def install_fake_core(
    monkeypatch: pytest.MonkeyPatch,
    runtime_client: FakeRuntimeClient,
) -> FakeRuntimeClient:
    """Install a fake ``agent_assembly._core`` whose ``RuntimeClient.connect``
    returns ``runtime_client``. Returns the same client for assertions."""

    class _ConnectingRuntimeClient:
        @staticmethod
        def connect(_socket_path: str) -> FakeRuntimeClient:
            return runtime_client

    fake_core = types.ModuleType("agent_assembly._core")
    fake_core.RuntimeClient = _ConnectingRuntimeClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "agent_assembly._core", fake_core)
    return runtime_client
