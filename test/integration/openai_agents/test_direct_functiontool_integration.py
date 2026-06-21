"""Integration test against the real ``agents`` (openai-agents) framework.

WHY this uses the real framework (AAASM-3528): the bug was that the adapter
patched a non-existent ``openai.agents.FunctionTool.__call__``, so it silently
never intercepted anything (fail-open). This test installs the patch and then
drives a genuine ``agents.function_tool`` exactly as the framework's runner does
— ``tool.on_invoke_tool(ctx, args_json)`` — asserting the call is governed. If
the patch reverts to a no-op, the denied tool would execute and this test fails.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_assembly.adapters.openai_agents import patch as openai_patch


def _make_tool_context(tool_name: str) -> Any:
    """Build the real ``ToolContext`` the framework passes to ``on_invoke_tool``."""
    from agents.tool_context import ToolContext

    return ToolContext(
        context=None,
        tool_name=tool_name,
        tool_call_id=f"call-{tool_name}",
        tool_arguments="{}",
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_real_openai_agents_functiontool_is_governed() -> None:
    pytest.importorskip("agents")
    from agents import function_tool

    recorded: list[str] = []

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            if kwargs.get("tool_name") == "blocked_tool":
                return {"status": "deny", "reason": "blocked by policy"}
            return {"status": "allow"}

        async def record_result(self, **kwargs: object) -> None:
            recorded.append(str(kwargs.get("tool_name")))

    patcher = openai_patch.OpenAIAgentsPatch(callback_handler=Interceptor(), process_agent_id="agent-oa")
    try:
        assert patcher.apply() is True

        # Tools constructed AFTER apply() get their real on_invoke_tool wrapped.
        @function_tool(name_override="blocked_tool")
        def blocked_tool(value: str) -> str:
            """A real tool whose body must NOT run when denied."""
            return f"executed:{value}"

        @function_tool(name_override="safe_tool")
        def safe_tool(value: str) -> str:
            """A real tool that is allowed and must run."""
            return "real-output"

        ctx_blocked = _make_tool_context("blocked_tool")
        ctx_safe = _make_tool_context("safe_tool")

        blocked_result = await blocked_tool.on_invoke_tool(ctx_blocked, '{"value": "x"}')
        safe_result = await safe_tool.on_invoke_tool(ctx_safe, '{"value": "x"}')
    finally:
        patcher.revert()

    # Denied: governance error string returned, tool body NOT executed.
    assert isinstance(blocked_result, str)
    assert "blocked by policy" in blocked_result
    assert "executed:" not in blocked_result

    # Allowed: real tool output returned and result recorded.
    assert safe_result == "real-output"
    assert "safe_tool" in recorded


@pytest.mark.asyncio
@pytest.mark.integration
async def test_real_functiontool_runs_ungoverned_after_revert() -> None:
    """Negative control: after revert, a deny decision no longer blocks — proving
    the governed state above is a real (non-no-op) interception."""
    pytest.importorskip("agents")
    from agents import function_tool

    class DenyAll:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "deny", "reason": "should not apply after revert"}

    patcher = openai_patch.OpenAIAgentsPatch(callback_handler=DenyAll(), process_agent_id="agent-oa")
    assert patcher.apply() is True
    patcher.revert()

    @function_tool
    def ungoverned(value: str) -> str:
        """Constructed after revert — must run normally."""
        return f"executed:{value}"

    ctx = _make_tool_context("ungoverned")
    result = await ungoverned.on_invoke_tool(ctx, '{"value": "y"}')

    assert result == "executed:y"
