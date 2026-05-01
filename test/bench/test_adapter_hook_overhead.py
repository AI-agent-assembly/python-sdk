"""Benchmark per-adapter hook register/unregister overhead.

Measures the wall-clock time of each adapter's register_hooks() +
unregister_hooks() cycle using a no-op governance interceptor to
isolate adapter wiring overhead from framework execution.

Contract: each adapter cycle must complete in <2ms P99 (AAASM-45).
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_assembly.adapters.crewai import patch as crewai_patch_mod
from agent_assembly.adapters.crewai.adapter import CrewAIAdapter
from agent_assembly.adapters.langchain.adapter import LangChainAdapter
from agent_assembly.adapters.langgraph import patch as langgraph_patch_mod
from agent_assembly.adapters.langgraph.adapter import LangGraphAdapter
from agent_assembly.adapters.mcp import patch as mcp_patch_mod
from agent_assembly.adapters.mcp.adapter import MCPAdapter
from agent_assembly.adapters.openai_agents import patch as openai_patch_mod
from agent_assembly.adapters.openai_agents.adapter import OpenAIAgentsAdapter
from agent_assembly.adapters.pydantic_ai import patch as pydantic_ai_patch_mod
from agent_assembly.adapters.pydantic_ai.adapter import PydanticAIAdapter

# ---------------------------------------------------------------------------
# Fake framework classes used to satisfy adapter loader checks
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


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------


@pytest.mark.benchmark(group="adapter-hook")
def test_crewai_hook_overhead(
    benchmark: Any,
    noop_interceptor: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(crewai_patch_mod, "_load_crewai_basetool_class", lambda: _FakeBaseTool)
    monkeypatch.setattr(crewai_patch_mod, "_load_crewai_task_class", lambda: _FakeTask)

    def cycle() -> None:
        adapter = CrewAIAdapter()
        adapter.register_hooks(noop_interceptor)
        adapter.unregister_hooks()

    benchmark(cycle)


@pytest.mark.benchmark(group="adapter-hook")
def test_langchain_hook_overhead(
    benchmark: Any,
    noop_interceptor: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # LangChainPatch.apply() always succeeds — it creates a callback handler.
    # Reset runtime state between iterations to measure cold-start wiring.
    def cycle() -> None:
        adapter = LangChainAdapter()
        adapter.register_hooks(noop_interceptor)
        adapter.unregister_hooks()

    benchmark(cycle)


@pytest.mark.benchmark(group="adapter-hook")
def test_langgraph_hook_overhead(
    benchmark: Any,
    noop_interceptor: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(langgraph_patch_mod, "_load_stategraph_class", lambda: _FakeStateGraph)

    def cycle() -> None:
        adapter = LangGraphAdapter()
        adapter.register_hooks(noop_interceptor)
        adapter.unregister_hooks()

    benchmark(cycle)


@pytest.mark.benchmark(group="adapter-hook")
def test_pydantic_ai_hook_overhead(
    benchmark: Any,
    noop_interceptor: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pydantic_ai_patch_mod, "_load_pydantic_ai_tool_class", lambda: _FakePydanticAITool)

    def cycle() -> None:
        adapter = PydanticAIAdapter()
        adapter.register_hooks(noop_interceptor)
        adapter.unregister_hooks()

    benchmark(cycle)


@pytest.mark.benchmark(group="adapter-hook")
def test_openai_agents_hook_overhead(
    benchmark: Any,
    noop_interceptor: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        openai_patch_mod,
        "_load_openai_agents_function_tool_class",
        lambda: _FakeOpenAIFunctionTool,
    )

    def cycle() -> None:
        adapter = OpenAIAgentsAdapter()
        adapter.register_hooks(noop_interceptor)
        adapter.unregister_hooks()

    benchmark(cycle)


@pytest.mark.benchmark(group="adapter-hook")
def test_mcp_hook_overhead(
    benchmark: Any,
    noop_interceptor: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_patch_mod, "_load_mcp_client_session_class", lambda: _FakeMCPClientSession)

    def cycle() -> None:
        adapter = MCPAdapter()
        adapter.register_hooks(noop_interceptor)
        adapter.unregister_hooks()

    benchmark(cycle)
