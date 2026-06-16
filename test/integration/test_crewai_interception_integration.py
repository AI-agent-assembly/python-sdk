from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters.crewai import patch as crewai_patch


@pytest.mark.integration
def test_crewai_two_task_flow_continues_after_blocked_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeBaseTool:
        def __init__(self, name: str) -> None:
            self.name = name

        def run(self, *args: Any, **kwargs: Any) -> str:
            del args, kwargs
            return f"ok:{self.name}"

    class FakeTask:
        def __init__(self, tool: FakeBaseTool, description: str, expected_output: str) -> None:
            self.tool = tool
            self.description = description
            self.expected_output = expected_output

        def execute_sync(self, *args: Any, **kwargs: Any) -> str:
            del args, kwargs
            return self.tool.run()

    fake_crewai_tools = SimpleNamespace(BaseTool=FakeBaseTool)
    fake_crewai_module = SimpleNamespace(Task=FakeTask)

    def fake_import_module(module_name: str) -> object:
        if module_name == "crewai.tools":
            return fake_crewai_tools
        if module_name == "crewai":
            return fake_crewai_module
        raise ImportError(module_name)

    monkeypatch.setattr(crewai_patch.importlib, "import_module", fake_import_module)

    class Interceptor:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            tool_name = kwargs.get("tool_name")
            if tool_name == "blocked_tool":
                return {"status": "deny", "reason": "blocked by policy"}
            return {"status": "allow"}

    patcher = crewai_patch.CrewAIPatch(Interceptor())
    assert patcher.apply() is True

    blocked_task = FakeTask(
        tool=FakeBaseTool("blocked_tool"),
        description="task1",
        expected_output="blocked string",
    )
    safe_task = FakeTask(
        tool=FakeBaseTool("safe_tool"),
        description="task2",
        expected_output="normal result",
    )

    results = [
        blocked_task.execute_sync(agent_id="agent-1"),
        safe_task.execute_sync(agent_id="agent-2"),
    ]

    assert isinstance(results[0], str)
    assert "[BLOCKED by governance policy]" in results[0]
    assert "blocked by policy" in results[0]
    assert results[1] == "ok:safe_tool"


@pytest.mark.integration
def test_crewai_real_task_and_tool_classes_flow_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crewai = pytest.importorskip("crewai")
    crewai_tools = pytest.importorskip("crewai.tools")

    BaseTool = crewai_tools.BaseTool
    Task = crewai.Task
    Agent = crewai.Agent
    Crew = crewai.Crew

    class BlockedTool(BaseTool):  # type: ignore[misc,valid-type]  # base is a runtime-imported framework class
        name: str = "blocked_tool"
        description: str = "Tool that should be blocked by governance."

        def _run(self, **kwargs: object) -> str:
            del kwargs
            return "should-not-run"

    class SafeTool(BaseTool):  # type: ignore[misc,valid-type]  # base is a runtime-imported framework class
        name: str = "safe_tool"
        description: str = "Tool that should remain allowed."

        def _run(self, **kwargs: object) -> str:
            del kwargs
            return "ok:safe_tool"

    def fake_execute_sync(self: object, *args: object, **kwargs: object) -> str:
        del args, kwargs
        task_tools = getattr(self, "tools", None) or []
        if task_tools:
            return str(task_tools[0].run())
        return "no-tool"

    monkeypatch.setattr(Task, "execute_sync", fake_execute_sync, raising=True)

    class Interceptor:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            if kwargs.get("tool_name") == "blocked_tool":
                return {"status": "deny", "reason": "blocked by policy"}
            return {"status": "allow"}

    patcher = crewai_patch.CrewAIPatch(Interceptor())
    assert patcher.apply() is True

    blocked_agent = Agent(role="blocked", goal="run blocked task", backstory="blocked")
    safe_agent = Agent(role="safe", goal="run safe task", backstory="safe")

    blocked_task = Task(
        description="blocked task",
        expected_output="blocked string",
        agent=blocked_agent,
        tools=[BlockedTool()],
    )
    safe_task = Task(
        description="safe task",
        expected_output="safe string",
        agent=safe_agent,
        tools=[SafeTool()],
    )

    # Build a real CrewAI Crew object to validate object wiring and two-agent task setup.
    Crew(agents=[blocked_agent, safe_agent], tasks=[blocked_task, safe_task], verbose=False)

    results = [
        blocked_task.execute_sync(agent_id="agent-1"),
        safe_task.execute_sync(agent_id="agent-2"),
    ]

    assert isinstance(results[0], str)
    assert "[BLOCKED by governance policy]" in results[0]
    assert "blocked by policy" in results[0]
    assert results[1] == "ok:safe_tool"
