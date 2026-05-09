"""Spawn context propagation via ContextVar for child agent lineage."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(slots=True)
class SpawnContext:
    """Lineage context set by a framework adapter at a spawn point."""

    parent_agent_id: str
    depth: int
    spawned_by_tool: str | None = None
    delegation_reason: str | None = None


_SPAWN_CTX: ContextVar[SpawnContext | None] = ContextVar("_spawn_ctx", default=None)


@contextmanager
def spawn_context_scope(ctx: SpawnContext) -> Generator[None, None, None]:
    """Set _SPAWN_CTX for the duration of the block; reset on exit."""
    token = _SPAWN_CTX.set(ctx)
    try:
        yield
    finally:
        _SPAWN_CTX.reset(token)
