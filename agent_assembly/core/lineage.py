"""In-memory agent lineage registry for parent/child graph traversal."""

from __future__ import annotations

from threading import Lock


class LineageRegistry:
    """Thread-safe in-memory registry mapping agents to their parents.

    Agents register with an optional parent_agent_id that reflects the
    SpawnContext set by framework adapters at spawn time.  The graph is
    a forest (one or more trees); cycles are not possible because
    parent_agent_id is always set to an already-registered ancestor.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._parent: dict[str, str | None] = {}

    def record(self, agent_id: str, parent_agent_id: str | None = None) -> None:
        """Register an agent, optionally linking it to its parent."""
        with self._lock:
            self._parent[agent_id] = parent_agent_id

    def children_of(self, parent_id: str) -> list[str]:
        """Return all agent IDs whose direct parent is *parent_id*."""
        with self._lock:
            return [aid for aid, pid in self._parent.items() if pid == parent_id]

    def ancestors_of(self, agent_id: str) -> list[str]:
        """Return the chain of ancestors from direct parent up to the root.

        The first element is the direct parent; the last is the root agent.
        Returns an empty list for unknown or root agents.
        """
        ancestors: list[str] = []
        with self._lock:
            current = self._parent.get(agent_id)
            while current is not None:
                ancestors.append(current)
                current = self._parent.get(current)
        return ancestors

    def __len__(self) -> int:
        with self._lock:
            return len(self._parent)
