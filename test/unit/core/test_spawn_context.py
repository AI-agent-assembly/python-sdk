from __future__ import annotations

from typing import Any

import pytest

from agent_assembly.core.spawn import _SPAWN_CTX, SpawnContext, spawn_context_scope


class TestSpawnContext:
    def test_dataclass_fields(self) -> None:
        ctx = SpawnContext(parent_agent_id="parent-1", depth=2, spawned_by_tool="tool-x")
        assert ctx.parent_agent_id == "parent-1"
        assert ctx.depth == 2
        assert ctx.spawned_by_tool == "tool-x"

    def test_spawned_by_tool_defaults_to_none(self) -> None:
        ctx = SpawnContext(parent_agent_id="parent-1", depth=1)
        assert ctx.spawned_by_tool is None

    def test_delegation_reason_defaults_to_none(self) -> None:
        ctx = SpawnContext(parent_agent_id="parent-1", depth=1)
        assert ctx.delegation_reason is None

    def test_delegation_reason_stored(self) -> None:
        ctx = SpawnContext(parent_agent_id="p", depth=1, delegation_reason="langgraph_node:call_llm")
        assert ctx.delegation_reason == "langgraph_node:call_llm"

    def test_spawn_context_scope_sets_and_resets(self) -> None:
        assert _SPAWN_CTX.get() is None
        ctx = SpawnContext(parent_agent_id="p", depth=1)
        with spawn_context_scope(ctx):
            assert _SPAWN_CTX.get() is ctx
        assert _SPAWN_CTX.get() is None

    def test_spawn_context_scope_resets_on_exception(self) -> None:
        assert _SPAWN_CTX.get() is None
        ctx = SpawnContext(parent_agent_id="p", depth=1)
        with pytest.raises(RuntimeError), spawn_context_scope(ctx):
            raise RuntimeError("boom")
        assert _SPAWN_CTX.get() is None

    def test_spawn_context_scope_nested(self) -> None:
        outer = SpawnContext(parent_agent_id="outer", depth=1)
        inner = SpawnContext(parent_agent_id="inner", depth=2)
        with spawn_context_scope(outer):
            assert _SPAWN_CTX.get() is outer
            with spawn_context_scope(inner):
                assert _SPAWN_CTX.get() is inner
            assert _SPAWN_CTX.get() is outer


class TestInitAssemblySpawnContextAutoRead:
    """init_assembly() must auto-fill parent_agent_id/depth from _SPAWN_CTX."""

    def test_auto_reads_parent_agent_id_from_spawn_ctx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import MagicMock, patch

        from agent_assembly.core import assembly
        from agent_assembly.core.spawn import (
            SpawnContext,
            spawn_context_scope,
        )

        monkeypatch.setattr(assembly, "_ACTIVE_CONTEXT", None)

        captured: dict[str, Any] = {}

        def fake_gateway_client(**kwargs: Any) -> Any:
            captured.update(kwargs)
            m = MagicMock()
            m.gateway_url = "http://gw"
            m.agent_id = kwargs["agent_id"]
            m.api_key = kwargs["api_key"]
            return m

        spawn_ctx = SpawnContext(parent_agent_id="parent-agent", depth=1, spawned_by_tool="runner")

        with (
            patch("agent_assembly.core.assembly.GatewayClient", side_effect=fake_gateway_client),
            patch("agent_assembly.core.assembly._register_adapters", return_value=[]),
            patch("agent_assembly.core.assembly._start_network_layer", return_value=("sdk-only", lambda: None)),
            spawn_context_scope(spawn_ctx),
        ):
            ctx = assembly.init_assembly(
                gateway_url="http://gw",
                api_key="key",
                agent_id="child-agent",
                mode="sdk-only",
            )
            ctx.shutdown()

        assert captured["parent_agent_id"] == "parent-agent"
        assert captured["depth"] == 1
        assert captured["spawned_by_tool"] == "runner"

    def test_explicit_parent_agent_id_overrides_spawn_ctx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import MagicMock, patch

        from agent_assembly.core import assembly
        from agent_assembly.core.spawn import SpawnContext, spawn_context_scope

        monkeypatch.setattr(assembly, "_ACTIVE_CONTEXT", None)
        captured: dict[str, Any] = {}

        def fake_gateway_client(**kwargs: Any) -> Any:
            captured.update(kwargs)
            m = MagicMock()
            m.gateway_url = "http://gw"
            m.agent_id = kwargs["agent_id"]
            m.api_key = kwargs["api_key"]
            return m

        spawn_ctx = SpawnContext(parent_agent_id="ctx-parent", depth=2)

        with (
            patch("agent_assembly.core.assembly.GatewayClient", side_effect=fake_gateway_client),
            patch("agent_assembly.core.assembly._register_adapters", return_value=[]),
            patch("agent_assembly.core.assembly._start_network_layer", return_value=("sdk-only", lambda: None)),
            spawn_context_scope(spawn_ctx),
        ):
            ctx = assembly.init_assembly(
                gateway_url="http://gw",
                api_key="key",
                agent_id="child",
                mode="sdk-only",
                parent_agent_id="explicit-parent",
            )
            ctx.shutdown()

        assert captured["parent_agent_id"] == "explicit-parent"
        assert captured["depth"] == 2  # ctx-provided depth was still used
        assert captured.get("spawned_by_tool") is None  # ctx had no spawned_by_tool

    def test_no_spawn_ctx_leaves_parent_agent_id_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import MagicMock, patch

        from agent_assembly.core import assembly

        monkeypatch.setattr(assembly, "_ACTIVE_CONTEXT", None)
        captured: dict[str, Any] = {}

        def fake_gateway_client(**kwargs: Any) -> Any:
            captured.update(kwargs)
            m = MagicMock()
            m.gateway_url = "http://gw"
            m.agent_id = kwargs["agent_id"]
            m.api_key = kwargs["api_key"]
            return m

        with (
            patch("agent_assembly.core.assembly.GatewayClient", side_effect=fake_gateway_client),
            patch("agent_assembly.core.assembly._register_adapters", return_value=[]),
            patch("agent_assembly.core.assembly._start_network_layer", return_value=("sdk-only", lambda: None)),
        ):
            ctx = assembly.init_assembly(
                gateway_url="http://gw",
                api_key="key",
                agent_id="solo-agent",
                mode="sdk-only",
            )
            ctx.shutdown()

        assert captured.get("parent_agent_id") is None
        assert captured.get("depth") is None
