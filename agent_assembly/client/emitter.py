"""Fire-and-forget edge emission helper."""

from __future__ import annotations

import logging
import threading

from agent_assembly.client.gateway import GatewayClient

logger = logging.getLogger(__name__)


class EdgeEmitter:
    """Emits topology edges asynchronously without blocking the caller."""

    def __init__(self, client: GatewayClient) -> None:
        self._client = client

    def emit(
        self,
        source_agent_id: str,
        target_agent_id: str,
        edge_type: str,
        metadata: dict | None = None,
    ) -> None:
        """Schedule a fire-and-forget edge report on a daemon thread."""
        t = threading.Thread(
            target=self._send,
            args=(source_agent_id, target_agent_id, edge_type, metadata),
            daemon=True,
        )
        t.start()

    def _send(
        self,
        source_agent_id: str,
        target_agent_id: str,
        edge_type: str,
        metadata: dict | None,
    ) -> None:
        try:
            self._client.report_edge(source_agent_id, target_agent_id, edge_type, metadata)
        except Exception:
            logger.warning(
                "EdgeEmitter: failed to report edge %s -> %s (%s)",
                source_agent_id,
                target_agent_id,
                edge_type,
                exc_info=True,
            )
