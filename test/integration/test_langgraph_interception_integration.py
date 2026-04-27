from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from agent_assembly.adapters.langchain import AssemblyCallbackHandler, patch_stategraph_compile
from agent_assembly.exceptions import ToolExecutionBlockedError


class GraphInterceptor:
    def __init__(self) -> None:
        self.events: list[str] = []

    def check_tool_start(self, **kwargs: object) -> dict[str, str]:
        serialized = kwargs.get("serialized")
        if isinstance(serialized, dict) and serialized.get("name") == "blocked_tool":
            return {"status": "deny", "reason": "blocked by policy"}
        return {"status": "allow"}

    def on_graph_node_start(self, **kwargs: object) -> None:
        self.events.append(f"start:{kwargs.get('node_name')}")

    def on_graph_node_end(self, **kwargs: object) -> None:
        self.events.append(f"end:{kwargs.get('node_name')}")


@pytest.mark.integration
def test_langgraph_compile_patch_wraps_multi_node_graph_and_blocks_denied_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interceptor = GraphInterceptor()
    handler = AssemblyCallbackHandler(interceptor)

    class FakeCompiledGraph:
        def __init__(self) -> None:
            self.nodes = {
                "node_a": self._node_a,
                "node_b": self._node_b,
            }

        def _node_a(self, state: dict[str, object]) -> dict[str, object]:
            handler.on_tool_start(
                serialized={"name": "safe_tool"},
                input_str="{}",
                run_id=uuid4(),
            )
            return {**state, "node_a": "ok"}

        def _node_b(self, state: dict[str, object]) -> dict[str, object]:
            handler.on_tool_start(
                serialized={"name": "blocked_tool"},
                input_str="{}",
                run_id=uuid4(),
            )
            return {**state, "node_b": "should-not-complete"}

        def invoke(self, state: dict[str, object]) -> dict[str, object]:
            current_state = state
            for node_name in ("node_a", "node_b"):
                current_state = self.nodes[node_name](current_state)
            return current_state

    class FakeStateGraph:
        def compile(self) -> FakeCompiledGraph:
            return FakeCompiledGraph()

    fake_module = SimpleNamespace(StateGraph=FakeStateGraph)

    def fake_import_module(module_name: str) -> object:
        if module_name == "langgraph.graph.state":
            return fake_module
        raise ImportError(module_name)

    monkeypatch.setattr(
        "agent_assembly.adapters.langchain.langgraph_patch.importlib.import_module",
        fake_import_module,
    )

    patched = patch_stategraph_compile(handler)
    assert patched is True

    compiled = FakeStateGraph().compile()
    with pytest.raises(ToolExecutionBlockedError):
        compiled.invoke({"step": "run"})

    assert interceptor.events == [
        "start:node_a",
        "end:node_a",
        "start:node_b",
    ]
