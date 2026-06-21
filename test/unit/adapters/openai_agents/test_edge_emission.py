"""Tests for OpenAI Agents handoff DelegatesTo edge emission."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_assembly.adapters.openai_agents.patch import (
    _apply_handoff_patch,
    _revert_handoff_patch,
    _wrap_on_invoke_handoff,
    set_edge_emitter,
    set_process_agent_id,
)

_HANDOFF_PATCHED_FLAG = "_agent_assembly_openai_agents_handoff_patched"
_ORIGINAL_HANDOFF_INIT = "_agent_assembly_original_openai_agents_handoff_init"


class RecordingEdgeEmitter:
    """Synchronous test double that records emitted edges."""

    def __init__(self) -> None:
        self.edges: list[tuple[str, str, str, dict[str, Any] | None]] = []

    def emit(self, source: str, target: str, edge_type: str, metadata: dict[str, Any] | None = None) -> None:
        self.edges.append((source, target, edge_type, metadata))


class FakeHandoff:
    """Stand-in for ``agents.Handoff`` — delegation via ``on_invoke_handoff``."""

    def __init__(self, agent_name: str = "agent_b", tool_description: str = "Transfer to B") -> None:
        self.agent_name = agent_name
        self.tool_description = tool_description

        async def _invoke(ctx: Any, input_json: Any) -> str:
            return "handoff-result"

        self.on_invoke_handoff = _invoke


class TestHandoffEdgeEmission:
    def setup_method(self) -> None:
        set_process_agent_id("agent-a")
        for attr in (_HANDOFF_PATCHED_FLAG, _ORIGINAL_HANDOFF_INIT):
            if hasattr(FakeHandoff, attr):
                delattr(FakeHandoff, attr)

    def teardown_method(self) -> None:
        _revert_handoff_patch(FakeHandoff)
        set_process_agent_id(None)
        set_edge_emitter(None)
        for attr in (_HANDOFF_PATCHED_FLAG, _ORIGINAL_HANDOFF_INIT):
            if hasattr(FakeHandoff, attr):
                delattr(FakeHandoff, attr)

    @pytest.mark.asyncio
    async def test_delegates_to_edge_emitted_on_handoff(self) -> None:
        emitter = RecordingEdgeEmitter()
        set_edge_emitter(emitter)
        _apply_handoff_patch(FakeHandoff, "agent-a")

        h = FakeHandoff(agent_name="agent_b", tool_description="Transfer to B")
        await h.on_invoke_handoff(MagicMock(), "{}")

        assert len(emitter.edges) == 1
        src, tgt, etype, meta = emitter.edges[0]
        assert src == "agent-a"
        assert tgt == "agent_b"
        assert etype == "delegates_to"
        assert isinstance(meta, dict)
        assert meta.get("reason") == "Transfer to B"

    @pytest.mark.asyncio
    async def test_no_edge_emitted_when_emitter_is_none(self) -> None:
        set_edge_emitter(None)
        _apply_handoff_patch(FakeHandoff, "agent-a")

        h = FakeHandoff(agent_name="agent_b")
        await h.on_invoke_handoff(MagicMock(), "{}")  # Should not raise

    @pytest.mark.asyncio
    async def test_no_edge_emitted_when_process_agent_id_is_none(self) -> None:
        emitter = RecordingEdgeEmitter()
        set_edge_emitter(emitter)
        _apply_handoff_patch(FakeHandoff, None)

        h = FakeHandoff(agent_name="agent_b")
        await h.on_invoke_handoff(MagicMock(), "{}")

        assert emitter.edges == []

    @pytest.mark.asyncio
    async def test_target_falls_back_to_name_attribute(self) -> None:
        emitter = RecordingEdgeEmitter()
        set_edge_emitter(emitter)

        class NameOnlyHandoff:
            """Handoff with no agent_name but with name."""

            def __init__(self) -> None:
                self.name = "fallback_agent"
                self.agent_name = None

                async def _invoke(ctx: Any, input_json: Any) -> str:
                    return "handoff-result"

                self.on_invoke_handoff = _invoke

        h = NameOnlyHandoff()
        _wrap_on_invoke_handoff(h, "agent-a")
        await h.on_invoke_handoff(MagicMock(), "{}")

        assert len(emitter.edges) == 1
        assert emitter.edges[0][1] == "fallback_agent"
