"""Integration test against the real ``smolagents`` framework.

WHY this uses the real framework (AAASM-3528 / AAASM-3539): the failure mode to
guard against is an adapter that patches the wrong attribute and silently never
intercepts anything (fail-open no-op). This test installs the patch and then
drives a genuine ``smolagents.Tool`` subclass exactly as the agent runner does —
calling ``tool(**inputs)`` (which dispatches to ``Tool.__call__`` ->
``self.forward``) — asserting deny blocks the body and allow runs+records it. If
the patch reverts to a no-op, the denied tool's ``forward`` would execute and
this test fails.
"""

from __future__ import annotations

import pytest

from agent_assembly.adapters.smolagents import patch as smol_patch


@pytest.mark.integration
def test_real_smolagents_tool_is_governed() -> None:
    pytest.importorskip("smolagents")
    from smolagents import Tool

    recorded: list[str] = []

    class Interceptor:
        _enforce = True

        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            if kwargs.get("tool_name") == "blocked_tool":
                return {"status": "deny", "reason": "blocked by policy"}
            return {"status": "allow"}

        def record_result(self, **kwargs: object) -> None:
            recorded.append(str(kwargs.get("tool_name")))

    class BlockedTool(Tool):  # type: ignore[misc]  # base is a runtime-imported framework class (untyped)
        name = "blocked_tool"
        description = "A real tool whose body must NOT run when denied."
        inputs = {"value": {"type": "string", "description": "input value"}}
        output_type = "string"

        def forward(self, value: str) -> str:
            return f"executed:{value}"

    class SafeTool(Tool):  # type: ignore[misc]  # base is a runtime-imported framework class (untyped)
        name = "safe_tool"
        description = "A real tool that is allowed and must run."
        inputs = {"value": {"type": "string", "description": "input value"}}
        output_type = "string"

        def forward(self, value: str) -> str:
            return f"real-output:{value}"

    patcher = smol_patch.SmolagentsPatch(Interceptor())
    try:
        assert patcher.apply() is True

        blocked_result = BlockedTool()(value="x")
        safe_result = SafeTool()(value="x")
    finally:
        patcher.revert()

    # Denied: governance block message returned, the real forward() never ran.
    assert isinstance(blocked_result, str)
    assert "blocked by policy" in blocked_result
    assert "executed:" not in blocked_result

    # Allowed: real tool output returned and the result recorded.
    assert safe_result == "real-output:x"
    assert "safe_tool" in recorded


@pytest.mark.integration
def test_real_smolagents_tool_runs_ungoverned_after_revert() -> None:
    """Negative control: after revert, a deny verdict no longer blocks the body,
    proving the governed state above is real (non-no-op) interception."""
    pytest.importorskip("smolagents")
    from smolagents import Tool

    class DenyAll:
        _enforce = True

        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "deny", "reason": "should not apply after revert"}

    class EchoTool(Tool):  # type: ignore[misc]  # base is a runtime-imported framework class (untyped)
        name = "echo"
        description = "Echoes its input."
        inputs = {"value": {"type": "string", "description": "input value"}}
        output_type = "string"

        def forward(self, value: str) -> str:
            return f"executed:{value}"

    patcher = smol_patch.SmolagentsPatch(DenyAll())
    assert patcher.apply() is True
    patcher.revert()

    result = EchoTool()(value="y")

    assert result == "executed:y"
