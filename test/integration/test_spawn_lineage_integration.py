"""Cross-framework spawn lineage integration tests.

These tests exercise the full flow:
  framework spawn adapter sets _SPAWN_CTX
  → child calls init_assembly()
  → GatewayClient is constructed with correct lineage fields

No real framework (langgraph, crewai, etc.) is required — each test simulates
what a framework adapter's patch does (set _SPAWN_CTX in scope, call a callback
that calls init_assembly()).  GatewayClient is mocked to capture the call args.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_assembly.core.assembly import init_assembly
from agent_assembly.core.spawn import _SPAWN_CTX, SpawnContext, spawn_context_scope

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GW_URL = "http://localhost:8080"
_API_KEY = "test-key"


def _call_init_assembly(**kwargs: object) -> MagicMock:
    """Call init_assembly with GatewayClient mocked; return the mock instance."""
    with patch("agent_assembly.core.assembly.GatewayClient") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.register_agent = MagicMock(return_value=None)
        mock_instance.close = MagicMock(return_value=None)
        mock_instance.gateway_url = _GW_URL.rstrip("/")
        mock_instance.agent_id = kwargs.get("agent_id", "agent-assembly-default")
        mock_instance.api_key = _API_KEY
        mock_cls.return_value = mock_instance

        # Also patch out adapter registration and network layer — we only care
        # about what GatewayClient receives.
        with (
            patch("agent_assembly.core.assembly._register_adapters", return_value=[]),
            patch(
                "agent_assembly.core.assembly._start_network_layer",
                return_value=("sdk-only", lambda: None),
            ),
            patch("agent_assembly.core.assembly._ACTIVE_CONTEXT", None),
        ):
            ctx = init_assembly(
                gateway_url=_GW_URL,
                api_key=_API_KEY,
                **kwargs,  # type: ignore[arg-type]
            )
            ctx.shutdown()

        # Return the mock so callers can inspect keyword args
        return mock_cls


# ---------------------------------------------------------------------------
# Test 1: spawn context propagates to init_assembly via GatewayClient ctor
# ---------------------------------------------------------------------------


def test_spawn_ctx_propagates_to_init_assembly() -> None:
    """SpawnContext values are forwarded to GatewayClient when set in _SPAWN_CTX."""
    spawn_ctx = SpawnContext(
        parent_agent_id="parent-001",
        depth=1,
        spawned_by_tool="test_tool",
    )

    with spawn_context_scope(spawn_ctx):
        mock_cls = _call_init_assembly(agent_id="child-001")

    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs.get("parent_agent_id") == "parent-001"
    assert call_kwargs.get("depth") == 1
    assert call_kwargs.get("spawned_by_tool") == "test_tool"


# ---------------------------------------------------------------------------
# Test 2: explicit params override spawn context
# ---------------------------------------------------------------------------


def test_explicit_params_override_spawn_ctx() -> None:
    """Explicit parent_agent_id / depth args take precedence over _SPAWN_CTX."""
    spawn_ctx = SpawnContext(
        parent_agent_id="from-ctx",
        depth=2,
        spawned_by_tool="ctx_tool",
    )

    with spawn_context_scope(spawn_ctx):
        mock_cls = _call_init_assembly(
            agent_id="child-002",
            parent_agent_id="explicit-parent",
            depth=5,
        )

    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs.get("parent_agent_id") == "explicit-parent"
    assert call_kwargs.get("depth") == 5
    # spawned_by_tool was NOT overridden — falls through from ctx
    assert call_kwargs.get("spawned_by_tool") == "ctx_tool"


# ---------------------------------------------------------------------------
# Test 3: no spawn context — explicit params used as-is
# ---------------------------------------------------------------------------


def test_no_spawn_ctx_uses_explicit_params_only() -> None:
    """When _SPAWN_CTX is not set, only explicitly passed params reach GatewayClient."""
    assert _SPAWN_CTX.get() is None  # ensure no ambient context

    mock_cls = _call_init_assembly(
        agent_id="solo-001",
        parent_agent_id="explicit-only",
        depth=3,
    )

    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs.get("parent_agent_id") == "explicit-only"
    assert call_kwargs.get("depth") == 3


# ---------------------------------------------------------------------------
# Test 4: _SPAWN_CTX resets after spawn_context_scope exits
# ---------------------------------------------------------------------------


def test_ctx_resets_after_scope_exits() -> None:
    """_SPAWN_CTX is None outside the spawn_context_scope block."""
    ctx = SpawnContext(parent_agent_id="root", depth=0, spawned_by_tool=None)

    with spawn_context_scope(ctx):
        assert _SPAWN_CTX.get() is not None

    assert _SPAWN_CTX.get() is None


# ---------------------------------------------------------------------------
# Test 5: nested scopes propagate depth correctly and restore outer scope
# ---------------------------------------------------------------------------


def test_nested_scopes_propagate_depth() -> None:
    """Inner spawn_context_scope overrides outer; outer is restored on inner exit."""
    outer_ctx = SpawnContext(parent_agent_id="root", depth=1, spawned_by_tool="outer")
    inner_ctx = SpawnContext(parent_agent_id="child", depth=2, spawned_by_tool="inner")

    with spawn_context_scope(outer_ctx):
        assert _SPAWN_CTX.get() is not None
        assert _SPAWN_CTX.get().depth == 1  # type: ignore[union-attr]

        with spawn_context_scope(inner_ctx):
            assert _SPAWN_CTX.get() is not None
            assert _SPAWN_CTX.get().depth == 2  # type: ignore[union-attr]

        # inner exited — should be back to outer
        assert _SPAWN_CTX.get() is not None
        assert _SPAWN_CTX.get().depth == 1  # type: ignore[union-attr]

    # outer exited — should be None
    assert _SPAWN_CTX.get() is None


# ---------------------------------------------------------------------------
# Test 6: exception inside scope still resets _SPAWN_CTX
# ---------------------------------------------------------------------------


def test_exception_in_scope_still_resets_ctx() -> None:
    """_SPAWN_CTX is reset even when an exception is raised inside the scope."""
    ctx = SpawnContext(parent_agent_id="root", depth=0, spawned_by_tool=None)

    with pytest.raises(RuntimeError, match="intentional"), spawn_context_scope(ctx):
        assert _SPAWN_CTX.get() is not None
        raise RuntimeError("intentional")

    assert _SPAWN_CTX.get() is None
