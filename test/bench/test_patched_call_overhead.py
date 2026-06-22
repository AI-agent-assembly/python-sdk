"""Benchmark per-call overhead of patched framework functions.

Measures the governance interception overhead on each tool/function
call when hooks are active — the "hot path" overhead users pay on
every LLM or tool invocation while the SDK is active.

This directly addresses AAASM-195 AC1 by measuring the time delta
of calling a governance-patched no-op function vs the unpatched
baseline (which is effectively zero).

Contract: per-call overhead must be <2ms P99 (AAASM-45).
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest

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

# ---------------------------------------------------------------------------
# Fake framework classes — minimal stubs with the patched hot-path method
# ---------------------------------------------------------------------------


class _BenchBaseTool:
    name = "bench_tool"

    def run(self, *args: Any, **kwargs: Any) -> str:
        return "result"


class _BenchCompiledGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, Any] = {"node_a": _noop_node}


def _noop_node(state: Any) -> Any:
    return state


class _BenchStateGraph:
    def compile(self, *args: Any, **kwargs: Any) -> _BenchCompiledGraph:
        return _BenchCompiledGraph()


class _BenchPydanticAITool:
    name = "bench_tool"

    async def _run(self, ctx: Any, args: Any, **kwargs: Any) -> str:
        return "result"


class _BenchOpenAIFunctionTool:
    """Shaped like ``agents.FunctionTool``: per-instance ``on_invoke_tool``."""

    def __init__(self) -> None:
        self.name = "bench_tool"

        async def _invoke(ctx: Any, input_str: str) -> str:
            return "result"

        self.on_invoke_tool = _invoke


class _BenchMCPClientSession:
    async def call_tool(self, name: str, arguments: Any = None) -> str:
        return "result"


# ---------------------------------------------------------------------------
# Shared event loop for async benchmarks
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def bench_event_loop() -> Any:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Sync adapter benchmarks
# ---------------------------------------------------------------------------


@pytest.mark.benchmark(group="patched-call")
def test_crewai_patched_call_overhead(benchmark: Any, noop_interceptor: Any) -> None:
    """Benchmark per-call overhead of governance-patched BaseTool.run()."""
    _apply_basetool_run_patch(_BenchBaseTool, noop_interceptor)
    tool = _BenchBaseTool()

    try:
        benchmark(tool.run)
    finally:
        _revert_basetool_run_patch(_BenchBaseTool)


@pytest.mark.benchmark(group="patched-call")
def test_langchain_callback_overhead(benchmark: Any, noop_interceptor: Any) -> None:
    """Benchmark per-call overhead of LangChain callback handler dispatch."""
    handler = AssemblyCallbackHandler(noop_interceptor)
    run_id = uuid4()
    serialized: dict[str, Any] = {"name": "bench_tool"}
    input_str = "benchmark input"

    def callback_cycle() -> None:
        handler.on_tool_start(serialized, input_str, run_id=run_id)
        handler.on_tool_end("result", run_id=run_id)

    benchmark(callback_cycle)


@pytest.mark.benchmark(group="patched-call")
def test_langgraph_wrapped_node_overhead(benchmark: Any, noop_interceptor: Any) -> None:
    """Benchmark per-call overhead of a governance-wrapped graph node."""
    _apply_stategraph_compile_patch(_BenchStateGraph, noop_interceptor)

    try:
        graph = _BenchStateGraph()
        compiled = graph.compile()
        wrapped_node = compiled.nodes["node_a"]

        def call_node() -> Any:
            return wrapped_node({"key": "value"})

        benchmark(call_node)
    finally:
        _revert_stategraph_compile_patch(_BenchStateGraph)


# ---------------------------------------------------------------------------
# Async adapter benchmarks
# ---------------------------------------------------------------------------


@pytest.mark.benchmark(group="patched-call")
def test_pydantic_ai_patched_call_overhead(
    benchmark: Any,
    noop_interceptor: Any,
    bench_event_loop: asyncio.AbstractEventLoop,
) -> None:
    """Benchmark per-call overhead of governance-patched Tool._run()."""
    _apply_tool_run_patch(_BenchPydanticAITool, noop_interceptor)
    tool = _BenchPydanticAITool()
    ctx = type("FakeCtx", (), {"deps": None, "run_id": None})()

    try:

        def call() -> None:
            bench_event_loop.run_until_complete(tool._run(ctx, {}))

        benchmark(call)
    finally:
        _revert_tool_run_patch(_BenchPydanticAITool)


@pytest.mark.benchmark(group="patched-call")
def test_openai_agents_patched_call_overhead(
    benchmark: Any,
    noop_interceptor: Any,
    bench_event_loop: asyncio.AbstractEventLoop,
) -> None:
    """Benchmark per-call overhead of governance-wrapped FunctionTool.on_invoke_tool()."""
    _apply_function_tool_patch(_BenchOpenAIFunctionTool, noop_interceptor)
    tool = _BenchOpenAIFunctionTool()
    # The class patch wraps on_invoke_tool at construction; for instances built
    # before apply() (or stub classes) wrap directly to benchmark the hot path.
    _wrap_on_invoke_tool(tool, noop_interceptor)
    ctx = type("FakeCtx", (), {"agent_id": None})()

    try:

        def call() -> None:
            bench_event_loop.run_until_complete(tool.on_invoke_tool(ctx, "bench input"))

        benchmark(call)
    finally:
        _revert_function_tool_patch(_BenchOpenAIFunctionTool)


@pytest.mark.benchmark(group="patched-call")
def test_mcp_patched_call_overhead(
    benchmark: Any,
    noop_interceptor: Any,
    bench_event_loop: asyncio.AbstractEventLoop,
) -> None:
    """Benchmark per-call overhead of governance-patched ClientSession.call_tool()."""
    _apply_client_session_patch(_BenchMCPClientSession, noop_interceptor)
    session = _BenchMCPClientSession()

    try:

        def call() -> None:
            bench_event_loop.run_until_complete(session.call_tool("bench_tool", {"key": "value"}))

        benchmark(call)
    finally:
        _revert_client_session_patch(_BenchMCPClientSession)
