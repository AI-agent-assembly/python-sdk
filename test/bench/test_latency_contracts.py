"""Latency contract enforcement tests.

Uses time.perf_counter_ns() to measure operations over 100 iterations
and compute P50, P95, P99 percentiles. Tests FAIL if the contract
threshold is exceeded — this is intentional per AAASM-195 AC.

Per-call tests measure the governance interception overhead on each
patched function call (the "hot path"), not hook setup/teardown.

Contracts:
  - Per-call adapter hook overhead: <2ms (AAASM-45)
  - Detection overhead: <50ms on first call (AAASM-47)
"""

from __future__ import annotations

import asyncio
import time
from test.bench.conftest import MAX_DETECTION_NS, MAX_PER_CALL_NS
from typing import Any
from uuid import uuid4

import pytest

import agent_assembly.core.assembly as assembly_mod
from agent_assembly.adapters.crewai.patch import (
    _apply_basetool_run_patch,
    _revert_basetool_run_patch,
)
from agent_assembly.adapters.langchain.callback_handler import AssemblyCallbackHandler
from agent_assembly.adapters.langgraph.patch import (
    _apply_stategraph_compile_patch,
    _revert_stategraph_compile_patch,
)
from agent_assembly.adapters.mcp.patch import (
    _apply_client_session_patch,
    _revert_client_session_patch,
)
from agent_assembly.adapters.openai_agents.patch import (
    _apply_function_tool_patch,
    _revert_function_tool_patch,
    _wrap_on_invoke_tool,
)
from agent_assembly.adapters.pydantic_ai.patch import (
    _apply_tool_run_patch,
    _revert_tool_run_patch,
)
from agent_assembly.adapters.registry import AdapterRegistry
from agent_assembly.core.assembly import init_assembly

_ITERATIONS = 100


@pytest.fixture(autouse=True)
def _force_pure_python_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep init_assembly() hermetic whether or not the native ``_core`` extension
    is built (AAASM-4906, sibling of AAASM-4898).

    With a native ``.so`` present, ``_native_core_available()`` returns True and
    init dials a real gateway over gRPC (``connect_runtime_client`` /
    ``register_agent``); the cold-start contract stubs neither, so it would
    hang/fail. Forcing the pure-Python path (the CI default) keeps the latency
    measurement deterministic in both build modes.
    """
    monkeypatch.setattr(assembly_mod, "_native_core_available", lambda: False)


def _percentiles(samples: list[int]) -> tuple[float, float, float]:
    """Return (P50, P95, P99) from a list of nanosecond measurements."""
    sorted_samples = sorted(samples)
    n = len(sorted_samples)
    p50 = sorted_samples[int(n * 0.50)]
    p95 = sorted_samples[int(n * 0.95)]
    p99 = sorted_samples[int(n * 0.99)]
    return float(p50), float(p95), float(p99)


# ---------------------------------------------------------------------------
# Fake framework classes for per-call overhead measurement
# ---------------------------------------------------------------------------


class _FakeBaseTool:
    name = "bench_tool"

    def run(self, *args: Any, **kwargs: Any) -> str:
        return "result"


class _FakeCompiledGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, Any] = {"node_a": lambda state: state}


class _FakeStateGraph:
    def compile(self, *args: Any, **kwargs: Any) -> _FakeCompiledGraph:
        return _FakeCompiledGraph()


class _FakePydanticAITool:
    name = "bench_tool"

    async def _run(self, ctx: Any, args: Any, **kwargs: Any) -> str:
        return "result"


class _FakeOpenAIFunctionTool:
    """Shaped like ``agents.FunctionTool``: per-instance ``on_invoke_tool``."""

    def __init__(self) -> None:
        self.name = "bench_tool"

        async def _invoke(ctx: Any, input_str: str) -> str:
            return "result"

        self.on_invoke_tool = _invoke


class _FakeMCPClientSession:
    async def call_tool(self, name: str, arguments: Any = None) -> str:
        return "result"


class _NoopInterceptor:
    def __getattr__(self, name: str) -> Any:
        def noop(*args: Any, **kwargs: Any) -> None:
            pass

        return noop


# ---------------------------------------------------------------------------
# Per-call latency contract (<2ms) — patched function call overhead
# ---------------------------------------------------------------------------


def test_crewai_per_call_latency_under_2ms() -> None:
    """Fail if CrewAI patched BaseTool.run() P99 exceeds 2ms."""
    interceptor = _NoopInterceptor()
    _apply_basetool_run_patch(_FakeBaseTool, interceptor)
    tool = _FakeBaseTool()
    samples: list[int] = []

    try:
        for _ in range(_ITERATIONS):
            start = time.perf_counter_ns()
            tool.run()
            elapsed = time.perf_counter_ns() - start
            samples.append(elapsed)
    finally:
        _revert_basetool_run_patch(_FakeBaseTool)

    p50, p95, p99 = _percentiles(samples)
    assert p99 < MAX_PER_CALL_NS, (
        f"CrewAI patched call P99 = {p99 / 1e6:.3f}ms exceeds "
        f"{MAX_PER_CALL_NS / 1e6:.1f}ms contract. "
        f"P50={p50 / 1e6:.3f}ms P95={p95 / 1e6:.3f}ms"
    )


def test_langchain_per_call_latency_under_2ms() -> None:
    """Fail if LangChain callback handler dispatch P99 exceeds 2ms."""
    interceptor = _NoopInterceptor()
    handler = AssemblyCallbackHandler(interceptor)
    run_id = uuid4()
    serialized: dict[str, Any] = {"name": "bench_tool"}
    samples: list[int] = []

    for _ in range(_ITERATIONS):
        start = time.perf_counter_ns()
        handler.on_tool_start(serialized, "benchmark input", run_id=run_id)
        handler.on_tool_end("result", run_id=run_id)
        elapsed = time.perf_counter_ns() - start
        samples.append(elapsed)

    p50, p95, p99 = _percentiles(samples)
    assert p99 < MAX_PER_CALL_NS, (
        f"LangChain callback P99 = {p99 / 1e6:.3f}ms exceeds "
        f"{MAX_PER_CALL_NS / 1e6:.1f}ms contract. "
        f"P50={p50 / 1e6:.3f}ms P95={p95 / 1e6:.3f}ms"
    )


def test_langgraph_per_call_latency_under_2ms() -> None:
    """Fail if LangGraph wrapped node call P99 exceeds 2ms."""
    interceptor = _NoopInterceptor()
    _apply_stategraph_compile_patch(_FakeStateGraph, interceptor)

    try:
        graph = _FakeStateGraph()
        compiled = graph.compile()
        wrapped_node = compiled.nodes["node_a"]
        samples: list[int] = []

        for _ in range(_ITERATIONS):
            start = time.perf_counter_ns()
            wrapped_node({"key": "value"})
            elapsed = time.perf_counter_ns() - start
            samples.append(elapsed)
    finally:
        _revert_stategraph_compile_patch(_FakeStateGraph)

    p50, p95, p99 = _percentiles(samples)
    assert p99 < MAX_PER_CALL_NS, (
        f"LangGraph node call P99 = {p99 / 1e6:.3f}ms exceeds "
        f"{MAX_PER_CALL_NS / 1e6:.1f}ms contract. "
        f"P50={p50 / 1e6:.3f}ms P95={p95 / 1e6:.3f}ms"
    )


def test_pydantic_ai_per_call_latency_under_2ms() -> None:
    """Fail if Pydantic AI patched Tool._run() P99 exceeds 2ms."""
    interceptor = _NoopInterceptor()
    _apply_tool_run_patch(_FakePydanticAITool, interceptor)
    tool = _FakePydanticAITool()
    ctx = type("FakeCtx", (), {"deps": None, "run_id": None})()

    async def measure() -> list[int]:
        samples: list[int] = []
        for _ in range(_ITERATIONS):
            start = time.perf_counter_ns()
            await tool._run(ctx, {})
            elapsed = time.perf_counter_ns() - start
            samples.append(elapsed)
        return samples

    try:
        samples = asyncio.run(measure())
    finally:
        _revert_tool_run_patch(_FakePydanticAITool)

    p50, p95, p99 = _percentiles(samples)
    assert p99 < MAX_PER_CALL_NS, (
        f"Pydantic AI patched call P99 = {p99 / 1e6:.3f}ms exceeds "
        f"{MAX_PER_CALL_NS / 1e6:.1f}ms contract. "
        f"P50={p50 / 1e6:.3f}ms P95={p95 / 1e6:.3f}ms"
    )


def test_openai_agents_per_call_latency_under_2ms() -> None:
    """Fail if OpenAI Agents governed FunctionTool.on_invoke_tool() P99 exceeds 2ms."""
    interceptor = _NoopInterceptor()
    _apply_function_tool_patch(_FakeOpenAIFunctionTool, interceptor)
    tool = _FakeOpenAIFunctionTool()
    _wrap_on_invoke_tool(tool, interceptor)
    ctx = type("FakeCtx", (), {"agent_id": None})()

    async def measure() -> list[int]:
        samples: list[int] = []
        for _ in range(_ITERATIONS):
            start = time.perf_counter_ns()
            await tool.on_invoke_tool(ctx, "benchmark input")
            elapsed = time.perf_counter_ns() - start
            samples.append(elapsed)
        return samples

    try:
        samples = asyncio.run(measure())
    finally:
        _revert_function_tool_patch(_FakeOpenAIFunctionTool)

    p50, p95, p99 = _percentiles(samples)
    assert p99 < MAX_PER_CALL_NS, (
        f"OpenAI Agents patched call P99 = {p99 / 1e6:.3f}ms exceeds "
        f"{MAX_PER_CALL_NS / 1e6:.1f}ms contract. "
        f"P50={p50 / 1e6:.3f}ms P95={p95 / 1e6:.3f}ms"
    )


def test_mcp_per_call_latency_under_2ms() -> None:
    """Fail if MCP patched ClientSession.call_tool() P99 exceeds 2ms."""
    interceptor = _NoopInterceptor()
    _apply_client_session_patch(_FakeMCPClientSession, interceptor)
    session = _FakeMCPClientSession()

    async def measure() -> list[int]:
        samples: list[int] = []
        for _ in range(_ITERATIONS):
            start = time.perf_counter_ns()
            await session.call_tool("bench_tool", {"key": "value"})
            elapsed = time.perf_counter_ns() - start
            samples.append(elapsed)
        return samples

    try:
        samples = asyncio.run(measure())
    finally:
        _revert_client_session_patch(_FakeMCPClientSession)

    p50, p95, p99 = _percentiles(samples)
    assert p99 < MAX_PER_CALL_NS, (
        f"MCP patched call P99 = {p99 / 1e6:.3f}ms exceeds "
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


def test_init_assembly_coldstart_latency(monkeypatch: pytest.MonkeyPatch) -> None:
    """Measure init_assembly() cold-start P50/P95/P99."""
    samples: list[int] = []

    for _ in range(_ITERATIONS):
        monkeypatch.setattr(assembly_mod, "_ACTIVE_CONTEXT", None)

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
