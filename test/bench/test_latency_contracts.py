"""Latency contract enforcement tests.

Uses time.perf_counter_ns() to measure operations over 100 iterations
and compute P50, P95, P99 percentiles. Tests FAIL if the contract
threshold is exceeded — this is intentional per AAASM-195 AC.

Contracts:
  - Per-call adapter hook overhead: <2ms (AAASM-45)
  - Detection overhead: <50ms on first call (AAASM-47)
"""

from __future__ import annotations

import statistics
import time
from typing import Any

import pytest

from agent_assembly.adapters.crewai.adapter import CrewAIAdapter
from agent_assembly.adapters.crewai import patch as crewai_patch_mod
from agent_assembly.adapters.langchain.adapter import LangChainAdapter
from agent_assembly.adapters.langgraph.adapter import LangGraphAdapter
from agent_assembly.adapters.langgraph import patch as langgraph_patch_mod
from agent_assembly.adapters.mcp.adapter import MCPAdapter
from agent_assembly.adapters.mcp import patch as mcp_patch_mod
from agent_assembly.adapters.openai_agents.adapter import OpenAIAgentsAdapter
from agent_assembly.adapters.openai_agents import patch as openai_patch_mod
from agent_assembly.adapters.pydantic_ai.adapter import PydanticAIAdapter
from agent_assembly.adapters.pydantic_ai import patch as pydantic_ai_patch_mod
from agent_assembly.adapters.registry import AdapterRegistry
import agent_assembly.core.assembly as assembly_mod
from agent_assembly.core.assembly import init_assembly

from test.bench.conftest import MAX_PER_CALL_NS, MAX_DETECTION_NS

_ITERATIONS = 100


def _percentiles(samples: list[int]) -> tuple[float, float, float]:
    """Return (P50, P95, P99) from a list of nanosecond measurements."""
    sorted_samples = sorted(samples)
    n = len(sorted_samples)
    p50 = sorted_samples[int(n * 0.50)]
    p95 = sorted_samples[int(n * 0.95)]
    p99 = sorted_samples[int(n * 0.99)]
    return float(p50), float(p95), float(p99)


# ---------------------------------------------------------------------------
# Fake framework classes (same as test_adapter_hook_overhead.py)
# ---------------------------------------------------------------------------


class _FakeBaseTool:
    name = "bench_tool"

    def run(self, *args: Any, **kwargs: Any) -> None:
        pass


class _FakeTask:
    description = "bench task"
    expected_output = "bench output"

    def execute_sync(self, *args: Any, **kwargs: Any) -> None:
        pass


class _FakeStateGraph:
    def compile(self, *args: Any, **kwargs: Any) -> Any:
        return self


class _FakePydanticAITool:
    name = "bench_tool"

    async def _run(self, ctx: Any, args: Any, **kwargs: Any) -> None:
        pass


class _FakeOpenAIFunctionTool:
    name = "bench_tool"

    async def __call__(self, ctx: Any, input_str: str) -> str:
        return ""


class _FakeMCPClientSession:
    async def call_tool(self, name: str, arguments: Any = None) -> Any:
        pass


class _NoopInterceptor:
    def __getattr__(self, name: str) -> Any:
        def noop(*args: Any, **kwargs: Any) -> None:
            pass

        return noop


# ---------------------------------------------------------------------------
# Per-call latency contract (<2ms)
# ---------------------------------------------------------------------------


_ADAPTER_CONFIGS: list[tuple[str, type, dict[str, Any]]] = [
    ("crewai", CrewAIAdapter, {}),
    ("langchain", LangChainAdapter, {}),
    ("langgraph", LangGraphAdapter, {}),
    ("pydantic_ai", PydanticAIAdapter, {}),
    ("openai_agents", OpenAIAgentsAdapter, {}),
    ("mcp", MCPAdapter, {}),
]


@pytest.mark.parametrize(
    "adapter_name,adapter_cls,kwargs",
    _ADAPTER_CONFIGS,
    ids=[c[0] for c in _ADAPTER_CONFIGS],
)
def test_per_call_latency_under_2ms(
    adapter_name: str,
    adapter_cls: type,
    kwargs: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail if any adapter hook register+unregister P99 exceeds 2ms."""
    # Install fakes for frameworks that need them
    monkeypatch.setattr(crewai_patch_mod, "_load_crewai_basetool_class", lambda: _FakeBaseTool)
    monkeypatch.setattr(crewai_patch_mod, "_load_crewai_task_class", lambda: _FakeTask)
    monkeypatch.setattr(langgraph_patch_mod, "_load_stategraph_class", lambda: _FakeStateGraph)
    monkeypatch.setattr(pydantic_ai_patch_mod, "_load_pydantic_ai_tool_class", lambda: _FakePydanticAITool)
    monkeypatch.setattr(openai_patch_mod, "_load_openai_agents_function_tool_class", lambda: _FakeOpenAIFunctionTool)
    monkeypatch.setattr(mcp_patch_mod, "_load_mcp_client_session_class", lambda: _FakeMCPClientSession)

    interceptor = _NoopInterceptor()
    samples: list[int] = []

    for _ in range(_ITERATIONS):
        adapter = adapter_cls(**kwargs)
        start = time.perf_counter_ns()
        adapter.register_hooks(interceptor)
        adapter.unregister_hooks()
        elapsed = time.perf_counter_ns() - start
        samples.append(elapsed)

    p50, p95, p99 = _percentiles(samples)
    assert p99 < MAX_PER_CALL_NS, (
        f"{adapter_name} hook cycle P99 = {p99 / 1e6:.3f}ms exceeds "
        f"{MAX_PER_CALL_NS / 1e6:.1f}ms contract. "
        f"P50={p50 / 1e6:.3f}ms P95={p95 / 1e6:.3f}ms"
    )


# ---------------------------------------------------------------------------
# Detection latency contract (<50ms)
# ---------------------------------------------------------------------------


def test_detection_latency_under_50ms() -> None:
    """Fail if auto_detect() P99 exceeds 50ms."""
    samples: list[int] = []

    for _ in range(_ITERATIONS):
        registry = AdapterRegistry()
        # Make all adapters unavailable for fast detection
        for adapter in registry._registered.values():
            adapter.is_available = lambda: False  # type: ignore[method-assign]

        start = time.perf_counter_ns()
        registry.auto_detect()
        elapsed = time.perf_counter_ns() - start
        samples.append(elapsed)

    p50, p95, p99 = _percentiles(samples)
    assert p99 < MAX_DETECTION_NS, (
        f"auto_detect() P99 = {p99 / 1e6:.3f}ms exceeds "
        f"{MAX_DETECTION_NS / 1e6:.1f}ms contract. "
        f"P50={p50 / 1e6:.3f}ms P95={p95 / 1e6:.3f}ms"
    )


# ---------------------------------------------------------------------------
# init_assembly() cold-start latency
# ---------------------------------------------------------------------------


def test_init_assembly_coldstart_latency() -> None:
    """Measure init_assembly() cold-start P50/P95/P99."""
    samples: list[int] = []

    for _ in range(_ITERATIONS):
        assembly_mod._ACTIVE_CONTEXT = None

        start = time.perf_counter_ns()
        ctx = init_assembly(
            gateway_url="http://localhost:8080",
            api_key="bench-key",
            agent_id="bench-agent",
            mode="sdk-only",
        )
        elapsed = time.perf_counter_ns() - start
        ctx.shutdown()
        samples.append(elapsed)

    p50, p95, p99 = _percentiles(samples)
    # init_assembly combines detection + registration — use detection budget
    assert p99 < MAX_DETECTION_NS, (
        f"init_assembly() cold-start P99 = {p99 / 1e6:.3f}ms exceeds "
        f"{MAX_DETECTION_NS / 1e6:.1f}ms contract. "
        f"P50={p50 / 1e6:.3f}ms P95={p95 / 1e6:.3f}ms"
    )
