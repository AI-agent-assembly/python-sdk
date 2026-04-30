from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters.openai_agents import patch as openai_patch


def _install_fake_openai_agents_module(monkeypatch: pytest.MonkeyPatch) -> type[Any]:
    class FakeFunctionTool:
        async def __call__(self, ctx: Any, tool_input: Any) -> dict[str, Any]:
            return {"ctx": ctx, "tool_input": tool_input}

    fake_module = SimpleNamespace(FunctionTool=FakeFunctionTool)

    def fake_import_module(module_name: str) -> object:
        if module_name == "openai.agents":
            return fake_module
        raise ImportError(module_name)

    monkeypatch.setattr(openai_patch.importlib, "import_module", fake_import_module)
    monkeypatch.setattr(openai_patch.importlib.util, "find_spec", lambda package: object())
    return FakeFunctionTool


def test_apply_patches_functiontool_call_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    function_tool_cls = _install_fake_openai_agents_module(monkeypatch)
    patcher = openai_patch.OpenAIAgentsPatch(callback_handler=object())

    original_call = function_tool_cls.__call__
    assert patcher.apply() is True

    patched_call = function_tool_cls.__call__
    assert patched_call is not original_call

    assert patcher.apply() is True
    assert function_tool_cls.__call__ is patched_call
