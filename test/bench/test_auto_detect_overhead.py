"""Benchmark AdapterRegistry.auto_detect() scaling.

Measures detection overhead with varying numbers of available
frameworks (0, 1, 2, 4) by controlling which adapters report
as available.

Contract: detection must complete in <50ms P99 (AAASM-47).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from agent_assembly.adapters.registry import AdapterRegistry

from test.bench.conftest import MAX_DETECTION_NS


def _make_registry_with_n_available(n: int) -> AdapterRegistry:
    """Create a registry where exactly *n* builtin adapters are 'available'."""
    registry = AdapterRegistry()
    adapters = list(registry._registered.values())
    for i, adapter in enumerate(adapters):
        if i < n:
            adapter.is_available = lambda: True  # type: ignore[assignment]
            # Provide a no-op register_hooks so auto_detect() succeeds
            adapter.register_hooks = lambda interceptor: None  # type: ignore[assignment]
            adapter.unregister_hooks = lambda: None  # type: ignore[assignment]
        else:
            adapter.is_available = lambda: False  # type: ignore[assignment]
    return registry


@pytest.mark.benchmark(group="detection")
@pytest.mark.parametrize("n_frameworks", [0, 1, 2, 4])
def test_auto_detect_scaling(benchmark: Any, n_frameworks: int) -> None:
    def detect() -> list[str]:
        registry = _make_registry_with_n_available(n_frameworks)
        return registry.auto_detect()

    result = benchmark(detect)
    assert len(result) == n_frameworks


@pytest.mark.benchmark(group="detection")
@pytest.mark.parametrize("n_frameworks", [0, 1, 2, 4])
def test_get_available_adapters_scaling(benchmark: Any, n_frameworks: int) -> None:
    def get_available() -> list[Any]:
        registry = _make_registry_with_n_available(n_frameworks)
        return registry.get_available_adapters_by_priority()

    result = benchmark(get_available)
    assert len(result) == n_frameworks
