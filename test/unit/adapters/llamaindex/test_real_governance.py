"""Governance proof against a real ``llama_index`` install.

Skipped when ``llama-index-core`` is not installed. When present, these tests
build a genuine ``FunctionTool`` and drive its real ``call`` / ``acall`` hooks
(the exact methods the LlamaIndex agent loop invokes) to prove a denied tool's
function body never executes, and an allowed one does and is recorded.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

pytest.importorskip("llama_index.core")

from llama_index.core.tools import FunctionTool  # noqa: E402
from llama_index.core.tools.types import ToolOutput  # noqa: E402

from agent_assembly.adapters.llamaindex import (  # noqa: E402
    LlamaIndexAdapter,
    LlamaIndexPatch,
)


class _AllowInterceptor:
    def __init__(self) -> None:
        self.recorded: list[object] = []

    def check_tool_start(self, **kwargs: object) -> dict[str, str]:
        del kwargs
        return {"status": "allow"}

    def on_tool_end(self, *, output: object, **kwargs: object) -> None:
        del kwargs
        self.recorded.append(output)


class _DenyInterceptor:
    def check_tool_start(self, **kwargs: object) -> dict[str, str]:
        del kwargs
        return {"status": "deny", "reason": "policy denied"}


@pytest.fixture
def restore_function_tool() -> Iterator[Callable[[LlamaIndexPatch], None]]:
    """Always revert the global ``FunctionTool`` patch after each test."""
    patches: list[LlamaIndexPatch] = []

    def track(patcher: LlamaIndexPatch) -> None:
        patches.append(patcher)

    yield track
    for patcher in patches:
        patcher.revert()


def test_real_denied_tool_body_never_runs(restore_function_tool: Callable[[LlamaIndexPatch], None]) -> None:
    side_effect: list[str] = []

    def dangerous_tool(target: str) -> str:
        side_effect.append(target)  # must never run under deny
        return f"deleted {target}"

    tool = FunctionTool.from_defaults(fn=dangerous_tool, name="dangerous_tool")

    patcher = LlamaIndexPatch(_DenyInterceptor())
    assert patcher.apply() is True
    restore_function_tool(patcher)

    result = tool.call(target="production-db")

    assert side_effect == []  # the real function body did not execute
    assert isinstance(result, ToolOutput)
    assert result.is_error is True
    assert "[BLOCKED by governance policy]" in result.content


@pytest.mark.asyncio
async def test_real_denied_async_tool_body_never_runs(restore_function_tool: Callable[[LlamaIndexPatch], None]) -> None:
    side_effect: list[str] = []

    async def dangerous_async_tool(target: str) -> str:
        side_effect.append(target)
        return f"deleted {target}"

    tool = FunctionTool.from_defaults(async_fn=dangerous_async_tool, name="dangerous_async_tool")

    patcher = LlamaIndexPatch(_DenyInterceptor())
    assert patcher.apply() is True
    restore_function_tool(patcher)

    result = await tool.acall(target="production-db")

    assert side_effect == []
    assert isinstance(result, ToolOutput)
    assert result.is_error is True
    assert "[BLOCKED by governance policy]" in result.content


def test_real_allowed_tool_runs_and_records(restore_function_tool: Callable[[LlamaIndexPatch], None]) -> None:
    side_effect: list[str] = []

    def safe_tool(value: str) -> str:
        side_effect.append(value)
        return f"ok {value}"

    tool = FunctionTool.from_defaults(fn=safe_tool, name="safe_tool")

    interceptor = _AllowInterceptor()
    patcher = LlamaIndexPatch(interceptor)
    assert patcher.apply() is True
    restore_function_tool(patcher)

    result = tool.call(value="hello")

    assert side_effect == ["hello"]
    assert isinstance(result, ToolOutput)
    assert result.is_error is False
    assert "ok hello" in result.content
    assert len(interceptor.recorded) == 1


def test_adapter_contract_and_availability() -> None:
    adapter = LlamaIndexAdapter()
    adapter.validate_registration()  # raises on contract violation
    assert adapter.get_framework_name() == "llama_index.core"
    assert adapter.get_supported_versions() == [">=0.10.0"]
    assert adapter.is_available() is True


def _unwrapped_call() -> object:
    """Underlying ``FunctionTool.call`` beneath LlamaIndex's instrumentation.

    LlamaIndex re-instruments ``call`` on every class-attribute assignment, so
    the wrapper object identity changes across patch/revert even though the
    wrapped function is the same. The wrapped function is the meaningful
    invariant to assert on.
    """
    raw = FunctionTool.__dict__["call"]
    return getattr(raw, "__wrapped__", raw)


def test_adapter_register_and_unregister_round_trip(restore_function_tool: Callable[[LlamaIndexPatch], None]) -> None:
    original_fn = _unwrapped_call()
    adapter = LlamaIndexAdapter()
    adapter.register(_DenyInterceptor())

    assert _unwrapped_call() is not original_fn

    def f(x: str) -> str:
        return f"ran {x}"

    blocked = FunctionTool.from_defaults(fn=f, name="f")
    result = blocked.call(x="y")
    assert isinstance(result, ToolOutput)
    assert result.is_error is True

    adapter.unregister_hooks()

    # Revert restores the original function and live behavior (body runs again).
    assert _unwrapped_call() is original_fn
    restored = FunctionTool.from_defaults(fn=f, name="f")
    assert restored.call(x="ok").content == "ran ok"
