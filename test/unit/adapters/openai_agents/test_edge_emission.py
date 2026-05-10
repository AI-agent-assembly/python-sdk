"""Tests for OpenAI Agents handoff DelegatesTo edge emission."""

from __future__ import annotations

from typing import Any

import pytest

from agent_assembly.adapters.openai_agents.patch import (
    _apply_handoff_call_patch,
    _revert_handoff_call_patch,
    set_edge_emitter,
    set_process_agent_id,
)

_HANDOFF_PATCHED_FLAG = "_agent_assembly_openai_agents_handoff_patched"
_ORIGINAL_HANDOFF_CALL = "_agent_assembly_original_openai_agents_handoff_call"


class RecordingEdgeEmitter:
    """Synchronous test double that records emitted edges."""

    def __init__(self) -> None:
        self.edges: list[tuple[str, str, str]] = []

    def emit(self, source: str, target: str, edge_type: str) -> None:
        self.edges.append((source, target, edge_type))


class FakeHandoff:
    """Minimal Handoff stand-in."""

    def __init__(self, agent_name: str = "agent_b") -> None:
        self.agent_name = agent_name

    async def __call__(self, *_args: Any, **_kwargs: Any) -> str:
        return "handoff-result"


class TestHandoffEdgeEmission:
    def setup_method(self) -> None:
        set_process_agent_id("agent-a")
        for attr in (_HANDOFF_PATCHED_FLAG, _ORIGINAL_HANDOFF_CALL):
            if hasattr(FakeHandoff, attr):
                delattr(FakeHandoff, attr)

    def teardown_method(self) -> None:
        _revert_handoff_call_patch(FakeHandoff)
        set_process_agent_id(None)
        set_edge_emitter(None)
        for attr in (_HANDOFF_PATCHED_FLAG, _ORIGINAL_HANDOFF_CALL):
            if hasattr(FakeHandoff, attr):
                delattr(FakeHandoff, attr)

    @pytest.mark.asyncio
    async def test_delegates_to_edge_emitted_on_handoff(self) -> None:
        emitter = RecordingEdgeEmitter()
        set_edge_emitter(emitter)
        _apply_handoff_call_patch(FakeHandoff, "agent-a")

        h = FakeHandoff(agent_name="agent_b")
        await h()

        assert len(emitter.edges) == 1
        src, tgt, etype = emitter.edges[0]
        assert src == "agent-a"
        assert tgt == "agent_b"
        assert etype == "delegates_to"

    @pytest.mark.asyncio
    async def test_no_edge_emitted_when_emitter_is_none(self) -> None:
        set_edge_emitter(None)
        _apply_handoff_call_patch(FakeHandoff, "agent-a")

        h = FakeHandoff(agent_name="agent_b")
        await h()  # Should not raise

    @pytest.mark.asyncio
    async def test_no_edge_emitted_when_process_agent_id_is_none(self) -> None:
        emitter = RecordingEdgeEmitter()
        set_edge_emitter(emitter)
        _apply_handoff_call_patch(FakeHandoff, None)

        h = FakeHandoff(agent_name="agent_b")
        await h()

        assert emitter.edges == []

    @pytest.mark.asyncio
    async def test_target_falls_back_to_name_attribute(self) -> None:
        emitter = RecordingEdgeEmitter()
        set_edge_emitter(emitter)

        class NameOnlyHandoff:
            """Handoff with no agent_name but with name."""

            name = "fallback_agent"
            agent_name: None = None

            async def __call__(self, *_args: Any, **_kwargs: Any) -> str:
                return "handoff-result"

        _apply_handoff_call_patch(NameOnlyHandoff, "agent-a")  # type: ignore[arg-type]
        h = NameOnlyHandoff()
        await h()

        assert len(emitter.edges) == 1
        assert emitter.edges[0][1] == "fallback_agent"
