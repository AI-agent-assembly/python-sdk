from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_assembly.adapters.langchain import AssemblyCallbackHandler, patch_stategraph_compile


class GraphInterceptor:
    def __init__(self) -> None:
        self.events: list[str] = []

    def on_graph_node_start(self, **kwargs: object) -> None:
        self.events.append(f"start:{kwargs.get('node_name')}")

    def on_graph_node_end(self, **kwargs: object) -> None:
        self.events.append(f"end:{kwargs.get('node_name')}")


@pytest.mark.integration
def test_langgraph_compile_patch_invokes_pre_post_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interceptor = GraphInterceptor()
    handler = AssemblyCallbackHandler(interceptor)

    class FakeCompiledGraph:
        def invoke(self, state: dict[str, object]) -> dict[str, object]:
            return {"ok": True, "input": state}

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
    result = compiled.invoke({"step": "run"})

    assert result == {"ok": True, "input": {"step": "run"}}
    assert interceptor.events == ["start:graph.invoke", "end:graph.invoke"]
