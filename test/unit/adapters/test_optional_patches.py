from __future__ import annotations

import pytest

from agent_assembly.adapters.openai_agents.patch import OpenAIAgentsPatch
from agent_assembly.adapters.openai_agents import patch as openai_patch

def test_openai_agents_patch_apply_and_revert(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openai_patch.importlib.util, "find_spec", lambda package: object())
    patcher = OpenAIAgentsPatch(callback_handler=object())
    assert patcher.apply() is True
    patcher.revert()


def test_openai_agents_patch_apply_returns_false_when_module_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(openai_patch.importlib.util, "find_spec", lambda package: None)
    patcher = OpenAIAgentsPatch(callback_handler=object())
    assert patcher.apply() is False
