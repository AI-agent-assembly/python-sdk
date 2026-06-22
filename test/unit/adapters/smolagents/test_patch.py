"""Unit tests for the smolagents governance patch.

These tests use a fake ``smolagents`` module (monkeypatched ``importlib``) so they
run even when the framework is not installed, mirroring the CrewAI adapter tests.
The *real-framework* governance proof — that ``deny`` blocks ``Tool.forward`` on a
genuine ``smolagents.Tool`` — lives in
``test/integration/smolagents/test_real_tool_governance.py``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters.smolagents import patch as smol_patch


class _RecordingInterceptor:
    """Allows everything and records each governed tool result."""

    def __init__(self, enforce: bool = True) -> None:
        self._enforce = enforce
        self.checked: list[dict[str, Any]] = []
        self.recorded: list[Any] = []

    def check_tool_start(self, **kwargs: Any) -> dict[str, str]:
        self.checked.append(kwargs)
        return {"status": "allow"}

    def record_result(self, **kwargs: Any) -> None:
        self.recorded.append(kwargs)


class _DenyInterceptor:
    def __init__(self, enforce: bool = True) -> None:
        self._enforce = enforce

    def check_tool_start(self, **kwargs: Any) -> dict[str, str]:
        del kwargs
        return {"status": "deny", "reason": "blocked by policy"}


def _install_fake_smolagents(monkeypatch: pytest.MonkeyPatch) -> type[Any]:
    """Install a fake ``smolagents`` module exposing a ``Tool`` whose ``__call__``
    runs a real (observable) body, so deny-blocking is testable."""

    class FakeTool:
        name = "fake_tool"

        def __call__(self, *args: Any, sanitize_inputs_outputs: bool = False, **kwargs: Any) -> dict[str, Any]:
            return {"ran": True, "sanitized": sanitize_inputs_outputs, "args": args, "kwargs": kwargs}

    fake_module = SimpleNamespace(Tool=FakeTool)

    def fake_import_module(module_name: str) -> object:
        if module_name == "smolagents":
            return fake_module
        raise ImportError(module_name)

    monkeypatch.setattr(smol_patch.importlib, "import_module", fake_import_module)
    return FakeTool


def test_apply_patches_tool_call_and_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTool = _install_fake_smolagents(monkeypatch)

    patcher = smol_patch.SmolagentsPatch(_RecordingInterceptor())
    assert patcher.apply() is True
    first_ref = FakeTool.__call__
    assert getattr(FakeTool, smol_patch._TOOL_PATCHED_FLAG, False) is True

    assert patcher.apply() is True
    assert FakeTool.__call__ is first_ref


def test_revert_restores_original_call(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTool = _install_fake_smolagents(monkeypatch)
    original_call = FakeTool.__call__

    patcher = smol_patch.SmolagentsPatch(_RecordingInterceptor())
    assert patcher.apply() is True
    assert FakeTool.__call__ is not original_call

    patcher.revert()
    assert FakeTool.__call__ is original_call
    assert getattr(FakeTool, smol_patch._TOOL_PATCHED_FLAG, False) is False


def test_allow_runs_tool_body_and_records_result(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTool = _install_fake_smolagents(monkeypatch)
    interceptor = _RecordingInterceptor()

    patcher = smol_patch.SmolagentsPatch(interceptor)
    assert patcher.apply() is True
    try:
        tool = FakeTool()
        result = tool(text="hello")
    finally:
        patcher.revert()

    # Real tool body executed and result was recorded by governance.
    assert result["ran"] is True
    assert interceptor.checked[0]["tool_name"] == "fake_tool"
    assert interceptor.checked[0]["args"] == {"text": "hello"}
    assert len(interceptor.recorded) == 1


def test_deny_blocks_tool_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """The core governance guarantee: a deny verdict short-circuits before the
    real tool body runs, returning the governance block message."""
    FakeTool = _install_fake_smolagents(monkeypatch)

    patcher = smol_patch.SmolagentsPatch(_DenyInterceptor())
    assert patcher.apply() is True
    try:
        tool = FakeTool()
        result = tool(text="hello")
    finally:
        patcher.revert()

    assert isinstance(result, str)
    assert "[BLOCKED by governance policy]" in result
    assert "blocked by policy" in result
    # The body returns a dict on success; a string proves it never executed.
    assert not isinstance(result, dict)


def test_noop_patch_negative_control(monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative control: without the patch applied, a deny interceptor cannot
    block the body. This fails if the adapter were ever reduced to a no-op,
    proving the deny path above is real interception (AAASM-3528 lesson)."""
    FakeTool = _install_fake_smolagents(monkeypatch)

    # No patch applied — deny interceptor exists but is never wired in.
    tool = FakeTool()
    result = tool(text="hello")

    assert isinstance(result, dict)
    assert result["ran"] is True


def test_sanitize_flag_excluded_from_governed_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """``sanitize_inputs_outputs`` is a framework control flag, not a tool input,
    so it must never appear in the arguments shown to governance policy."""
    FakeTool = _install_fake_smolagents(monkeypatch)
    interceptor = _RecordingInterceptor()

    patcher = smol_patch.SmolagentsPatch(interceptor)
    assert patcher.apply() is True
    try:
        tool = FakeTool()
        tool(text="hi", sanitize_inputs_outputs=True)
    finally:
        patcher.revert()

    governed_args = interceptor.checked[0]["args"]
    assert governed_args == {"text": "hi"}
    assert "sanitize_inputs_outputs" not in governed_args


def test_dict_positional_args_are_flattened(monkeypatch: pytest.MonkeyPatch) -> None:
    """smolagents supports ``tool({"x": 1})`` — the dict-arg convenience path.
    Those inputs must be surfaced to governance as named args."""
    FakeTool = _install_fake_smolagents(monkeypatch)
    interceptor = _RecordingInterceptor()

    patcher = smol_patch.SmolagentsPatch(interceptor)
    assert patcher.apply() is True
    try:
        tool = FakeTool()
        tool({"text": "world"})
    finally:
        patcher.revert()

    assert interceptor.checked[0]["args"] == {"text": "world"}


def test_apply_false_when_smolagents_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_import_error(module_name: str) -> object:
        raise ImportError(module_name)

    monkeypatch.setattr(smol_patch.importlib, "import_module", raise_import_error)
    assert smol_patch._load_smolagents_tool_class() is None
    assert smol_patch.SmolagentsPatch(_RecordingInterceptor()).apply() is False
