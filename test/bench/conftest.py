"""Shared fixtures and constants for performance benchmarks."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

# Latency contract thresholds (nanoseconds)
MAX_PER_CALL_NS = 2_000_000  # <2ms per-call overhead (AAASM-45)
MAX_DETECTION_NS = 50_000_000  # <50ms detection overhead (AAASM-47)


@pytest.fixture
def mock_gateway_client() -> MagicMock:
    """Return a MagicMock that satisfies GatewayClient interface."""
    client = MagicMock()
    client.gateway_url = "http://localhost:8080"
    client.api_key = "test-key"
    client.agent_id = "bench-agent"
    client.close = MagicMock()
    return client


@pytest.fixture
def noop_interceptor() -> _NoopInterceptor:
    """Return a no-op governance interceptor for benchmarking hooks."""
    return _NoopInterceptor()


class _NoopInterceptor:
    """Minimal interceptor that accepts any method call and returns None."""

    def __getattr__(self, name: str) -> Any:
        def noop(*args: Any, **kwargs: Any) -> None:
            del args, kwargs

        return noop
