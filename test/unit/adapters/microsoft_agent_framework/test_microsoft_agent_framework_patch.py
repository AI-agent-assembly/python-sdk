"""Unit tests for the Microsoft Agent Framework adapter patch.

These tests prove **real governance**, not a no-op (the AAASM-3528 lesson):

- A fake ``FunctionTool`` exercises the patch wiring without requiring the
  framework to be installed (so the suite runs in plain CI).
- A *negative control* records that the wrapped function actually runs when the
  verdict is ``allow`` and is *prevented* when the verdict is ``deny`` — a no-op
  patch would fail both halves.
- A guarded section drives the **real** ``agent_framework.FunctionTool`` when the
  package is importable, proving the chosen hook point genuinely intercepts.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters.microsoft_agent_framework import patch as maf_patch
from agent_assembly.exceptions import PolicyViolationError


class _AllowInterceptor:
    _enforce = True

    def __init__(self) -> None:
        self.checked: list[dict[str, Any]] = []
        self.recorded: list[dict[str, Any]] = []

    def check_tool_start(self, **kwargs: Any) -> dict[str, str]:
        self.checked.append(kwargs)
        return {"status": "allow"}

    def record_result(self, **kwargs: Any) -> None:
        self.recorded.append(kwargs)


class _DenyInterceptor:
    _enforce = True

    def check_tool_start(self, **kwargs: Any) -> dict[str, str]:
        del kwargs
        return {"status": "deny", "reason": "denied by policy"}


class _PendingThenDenyInterceptor:
    _enforce = True

    def check_tool_start(self, **kwargs: Any) -> dict[str, str]:
        del kwargs
        return {"status": "pending"}

    def wait_for_tool_approval(self, **kwargs: Any) -> dict[str, str]:
        del kwargs
        return {"status": "deny", "reason": "rejected at approval"}


def _install_fake_agent_framework(monkeypatch: pytest.MonkeyPatch, side_effects: list[Any]) -> type[Any]:
    """Install a fake ``agent_framework`` exposing a ``FunctionTool`` with ``invoke``."""

    class FakeFunctionTool:
        name = "fake_tool"

        async def invoke(self, *, arguments: Any = None, **kwargs: Any) -> str:
            del kwargs
            side_effects.append(("ran", arguments))
            return "real-result"

    fake_module = SimpleNamespace(FunctionTool=FakeFunctionTool)

    def fake_import_module(module_name: str) -> object:
        if module_name == "agent_framework":
            return fake_module
        raise ImportError(module_name)

    monkeypatch.setattr(maf_patch.importlib, "import_module", fake_import_module)
    return FakeFunctionTool


def test_apply_is_idempotent_and_revert_restores(monkeypatch: pytest.MonkeyPatch) -> None:
    side_effects: list[Any] = []
    FakeTool = _install_fake_agent_framework(monkeypatch, side_effects)
    original_invoke = FakeTool.invoke

    patcher = maf_patch.MicrosoftAgentFrameworkPatch(_AllowInterceptor())
    assert patcher.apply() is True
    patched_ref = FakeTool.invoke
    assert FakeTool.invoke is not original_invoke
    assert getattr(FakeTool, maf_patch._TOOLS_PATCHED_FLAG, False) is True

    # Second apply is a no-op: the patched method is not re-wrapped.
    assert patcher.apply() is True
    assert FakeTool.invoke is patched_ref

    patcher.revert()
    assert FakeTool.invoke is original_invoke
    assert getattr(FakeTool, maf_patch._TOOLS_PATCHED_FLAG, False) is False
    assert maf_patch._get_process_agent_id() is None


@pytest.mark.asyncio
async def test_allow_runs_tool_and_records_result(monkeypatch: pytest.MonkeyPatch) -> None:
    side_effects: list[Any] = []
    FakeTool = _install_fake_agent_framework(monkeypatch, side_effects)
    interceptor = _AllowInterceptor()

    patcher = maf_patch.MicrosoftAgentFrameworkPatch(interceptor)
    assert patcher.apply() is True

    result = await FakeTool().invoke(arguments={"city": "Seattle"})

    # Real governance: the wrapped function actually executed (negative control).
    assert side_effects == [("ran", {"city": "Seattle"})]
    assert result == "real-result"
    # The check observed the real tool name + args, and the result was recorded.
    assert interceptor.checked[0]["tool_name"] == "fake_tool"
    assert interceptor.checked[0]["args"] == {"city": "Seattle"}
    assert interceptor.recorded[0]["tool_name"] == "fake_tool"

    patcher.revert()


@pytest.mark.asyncio
async def test_deny_blocks_tool_and_prevents_side_effect(monkeypatch: pytest.MonkeyPatch) -> None:
    side_effects: list[Any] = []
    FakeTool = _install_fake_agent_framework(monkeypatch, side_effects)

    patcher = maf_patch.MicrosoftAgentFrameworkPatch(_DenyInterceptor())
    assert patcher.apply() is True

    tool = FakeTool()
    with pytest.raises(PolicyViolationError, match="blocked by governance policy"):
        await tool.invoke(arguments={"city": "Seattle"})

    # The wrapped function must NOT have run — a no-op patch would let it through.
    assert side_effects == []

    patcher.revert()


@pytest.mark.asyncio
async def test_pending_then_deny_rejects_at_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    side_effects: list[Any] = []
    FakeTool = _install_fake_agent_framework(monkeypatch, side_effects)

    patcher = maf_patch.MicrosoftAgentFrameworkPatch(_PendingThenDenyInterceptor())
    assert patcher.apply() is True

    tool = FakeTool()
    with pytest.raises(PolicyViolationError, match="rejected during approval"):
        await tool.invoke(arguments={"x": 1})

    assert side_effects == []

    patcher.revert()


@pytest.mark.asyncio
async def test_unknown_verdict_fails_closed_under_enforce(monkeypatch: pytest.MonkeyPatch) -> None:
    side_effects: list[Any] = []
    FakeTool = _install_fake_agent_framework(monkeypatch, side_effects)

    class _MalformedInterceptor:
        _enforce = True

        def check_tool_start(self, **kwargs: Any) -> dict[str, str]:
            del kwargs
            return {"status": "garbage"}

    patcher = maf_patch.MicrosoftAgentFrameworkPatch(_MalformedInterceptor())
    assert patcher.apply() is True

    tool = FakeTool()
    with pytest.raises(PolicyViolationError):
        await tool.invoke(arguments={"x": 1})
    assert side_effects == []

    patcher.revert()


@pytest.mark.asyncio
async def test_unknown_verdict_fails_open_without_enforce(monkeypatch: pytest.MonkeyPatch) -> None:
    side_effects: list[Any] = []
    FakeTool = _install_fake_agent_framework(monkeypatch, side_effects)

    class _ObserveInterceptor:
        # No ``_enforce`` attribute -> fail-open (observe / disabled posture).
        def check_tool_start(self, **kwargs: Any) -> dict[str, str]:
            del kwargs
            return {"status": "garbage"}

    patcher = maf_patch.MicrosoftAgentFrameworkPatch(_ObserveInterceptor())
    assert patcher.apply() is True

    result = await FakeTool().invoke(arguments={"x": 1})
    assert result == "real-result"
    assert side_effects == [("ran", {"x": 1})]

    patcher.revert()


def test_apply_is_noop_when_framework_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_import_error(module_name: str) -> object:
        raise ImportError(module_name)

    monkeypatch.setattr(maf_patch.importlib, "import_module", raise_import_error)
    assert maf_patch._load_function_tool_class() is None
    assert maf_patch.MicrosoftAgentFrameworkPatch(_AllowInterceptor()).apply() is False


def test_load_returns_none_for_non_type_attribute(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = SimpleNamespace(FunctionTool=object())

    def fake_import_module(module_name: str) -> object:
        if module_name == "agent_framework":
            return fake_module
        raise ImportError(module_name)

    monkeypatch.setattr(maf_patch.importlib, "import_module", fake_import_module)
    assert maf_patch._load_function_tool_class() is None


def test_serialize_tool_args_channels() -> None:
    class _Model:
        def model_dump(self) -> dict[str, Any]:
            return {"a": 1}

    # arguments= via a pydantic-like model
    assert maf_patch._serialize_tool_args(_Model(), None, {}) == {"a": 1}
    # arguments= via a plain mapping
    assert maf_patch._serialize_tool_args({"b": 2}, None, {}) == {"b": 2}
    # via context.arguments
    ctx = SimpleNamespace(arguments={"c": 3})
    assert maf_patch._serialize_tool_args(None, ctx, {}) == {"c": 3}
    # via direct kwargs
    assert maf_patch._serialize_tool_args(None, None, {"d": 4}) == {"d": 4}
    # empty
    assert maf_patch._serialize_tool_args(None, None, {}) == {}


# --- Real-framework governance proof (skips when agent-framework is absent) ---


@pytest.mark.asyncio
async def test_real_agent_framework_function_tool_is_governed() -> None:
    """Drive the REAL ``agent_framework.FunctionTool`` to prove a genuine hook.

    This is the decisive negative control against a fake adapter: with the
    actual package installed, a denied verdict must both raise and stop the
    wrapped function's side effect, while an allowed verdict must run it.
    """
    af = pytest.importorskip("agent_framework", reason="agent-framework not installed")
    from agent_assembly.adapters.microsoft_agent_framework import (
        MicrosoftAgentFrameworkAdapter,
    )

    side: list[tuple[str, str]] = []

    # AAASM-4434: mypy 2.x reclassified "decorator returns Any" from `misc` to its
    # own `untyped-decorator` code; `af` itself is `Any` (pytest.importorskip's
    # return type), so the decorator is untyped regardless of code.
    @af.tool  # type: ignore[untyped-decorator]  # framework decorator is untyped
    def write_note(path: str, content: str) -> str:
        """Write a note (records a side effect)."""
        side.append((path, content))
        return f"wrote {path}"

    adapter = MicrosoftAgentFrameworkAdapter()

    # Negative control: ungoverned call runs the side effect.
    side.clear()
    await write_note.invoke(arguments={"path": "/a", "content": "x"})
    assert side == [("/a", "x")]

    try:
        adapter.register(_DenyInterceptor())
        side.clear()
        with pytest.raises(PolicyViolationError):
            await write_note.invoke(arguments={"path": "/a", "content": "x"})
        assert side == []  # deny prevented the side effect
    finally:
        adapter.unregister_hooks()

    interceptor = _AllowInterceptor()
    try:
        adapter.register(interceptor)
        side.clear()
        await write_note.invoke(arguments={"path": "/b", "content": "y"})
        assert side == [("/b", "y")]  # allow ran the tool
        assert interceptor.recorded  # and recorded the result
    finally:
        adapter.unregister_hooks()


class _TerminalPendingInterceptor:
    _enforce = True

    def check_tool_start(self, **kwargs: Any) -> dict[str, str]:
        del kwargs
        return {"status": "pending"}

    def wait_for_tool_approval(self, **kwargs: Any) -> dict[str, str]:
        del kwargs
        return {"status": "pending", "reason": "still pending"}


@pytest.mark.asyncio
async def test_terminal_pending_blocks_tool_and_does_not_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """AAASM-4906: a still-"pending" verdict after the approval round-trip must
    fail closed — only an explicit allow may run the tool, matching LangChain."""
    side_effects: list[Any] = []
    FakeTool = _install_fake_agent_framework(monkeypatch, side_effects)

    patcher = maf_patch.MicrosoftAgentFrameworkPatch(_TerminalPendingInterceptor())
    assert patcher.apply() is True

    tool = FakeTool()
    with pytest.raises(PolicyViolationError, match="rejected during approval"):
        await tool.invoke(arguments={"x": 1})

    assert side_effects == []

    patcher.revert()
