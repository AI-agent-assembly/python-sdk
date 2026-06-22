"""Unit tests for the LlamaIndex governance patch.

These tests assert the security-relevant invariant directly: when policy
denies a tool, the tool's underlying function body must not run, and when it
allows, the body runs and the result is recorded. The negative-control test
(``test_negative_control_*``) proves the suite would FAIL if the patch were
reverted to a no-op pass-through — i.e. the tests genuinely exercise
governance rather than the framework's own happy path.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters.llamaindex import patch as li_patch


class _FakeMetadata:
    def __init__(self, name: str) -> None:
        self._name = name

    def get_name(self) -> str:
        return self._name


def _make_fake_function_tool_class(body: list[str]) -> type[Any]:
    """Build a fake ``FunctionTool`` whose sync/async bodies record execution."""

    class FakeFunctionTool:
        def __init__(self, name: str = "fake_tool") -> None:
            self.metadata = _FakeMetadata(name)

        def call(self, *args: Any, **kwargs: Any) -> dict[str, object]:
            body.append("call")
            return {"args": args, "kwargs": kwargs}

        async def acall(self, *args: Any, **kwargs: Any) -> dict[str, object]:
            body.append("acall")
            return {"args": args, "kwargs": kwargs}

    return FakeFunctionTool


class _FakeToolOutput:
    """Minimal stand-in for ``llama_index.core.tools.types.ToolOutput``."""

    def __init__(
        self,
        *,
        content: str,
        tool_name: str,
        raw_input: dict[str, object],
        raw_output: object,
        is_error: bool = False,
    ) -> None:
        self.content = content
        self.tool_name = tool_name
        self.raw_input = raw_input
        self.raw_output = raw_output
        self.is_error = is_error


def _install_fake_llamaindex(monkeypatch: pytest.MonkeyPatch, tool_cls: type[Any]) -> None:
    fake_tools = SimpleNamespace(FunctionTool=tool_cls)
    fake_types = SimpleNamespace(ToolOutput=_FakeToolOutput)

    def fake_import_module(module_name: str) -> object:
        if module_name == "llama_index.core.tools":
            return fake_tools
        if module_name == "llama_index.core.tools.types":
            return fake_types
        raise ImportError(module_name)

    monkeypatch.setattr(li_patch.importlib, "import_module", fake_import_module)


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
        return {"status": "deny", "reason": "blocked for safety"}


def test_apply_is_idempotent_and_revert_restores(monkeypatch: pytest.MonkeyPatch) -> None:
    body: list[str] = []
    tool_cls = _make_fake_function_tool_class(body)
    original_call = tool_cls.call
    original_acall = tool_cls.acall
    _install_fake_llamaindex(monkeypatch, tool_cls)

    patcher = li_patch.LlamaIndexPatch(_AllowInterceptor())
    assert patcher.apply() is True
    first_call_ref = tool_cls.call
    first_acall_ref = tool_cls.acall
    assert getattr(tool_cls, li_patch._TOOL_CALL_PATCHED_FLAG, False) is True
    assert getattr(tool_cls, li_patch._TOOL_ACALL_PATCHED_FLAG, False) is True

    assert patcher.apply() is True
    assert tool_cls.call is first_call_ref
    assert tool_cls.acall is first_acall_ref

    patcher.revert()
    assert tool_cls.call is original_call
    assert tool_cls.acall is original_acall
    assert getattr(tool_cls, li_patch._TOOL_CALL_PATCHED_FLAG, False) is False
    assert getattr(tool_cls, li_patch._TOOL_ACALL_PATCHED_FLAG, False) is False


def test_apply_false_when_llamaindex_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_import_error(module_name: str) -> object:
        raise ImportError(module_name)

    monkeypatch.setattr(li_patch.importlib, "import_module", raise_import_error)
    assert li_patch.LlamaIndexPatch(_AllowInterceptor()).apply() is False


def test_denied_sync_tool_does_not_run_body(monkeypatch: pytest.MonkeyPatch) -> None:
    body: list[str] = []
    tool_cls = _make_fake_function_tool_class(body)
    _install_fake_llamaindex(monkeypatch, tool_cls)

    patcher = li_patch.LlamaIndexPatch(_DenyInterceptor())
    assert patcher.apply() is True

    result = tool_cls().call(param="value")

    # Governance invariant: the tool body MUST NOT have executed.
    assert body == []
    assert isinstance(result, _FakeToolOutput)
    assert result.is_error is True
    assert "[BLOCKED by governance policy]" in result.content
    assert "blocked for safety" in result.content


def test_allowed_sync_tool_runs_and_records(monkeypatch: pytest.MonkeyPatch) -> None:
    body: list[str] = []
    tool_cls = _make_fake_function_tool_class(body)
    _install_fake_llamaindex(monkeypatch, tool_cls)

    interceptor = _AllowInterceptor()
    patcher = li_patch.LlamaIndexPatch(interceptor)
    assert patcher.apply() is True

    result = tool_cls().call(param="value")

    assert body == ["call"]
    assert result == {"args": (), "kwargs": {"param": "value"}}
    assert interceptor.recorded == [result]


@pytest.mark.asyncio
async def test_denied_async_tool_does_not_run_body(monkeypatch: pytest.MonkeyPatch) -> None:
    body: list[str] = []
    tool_cls = _make_fake_function_tool_class(body)
    _install_fake_llamaindex(monkeypatch, tool_cls)

    patcher = li_patch.LlamaIndexPatch(_DenyInterceptor())
    assert patcher.apply() is True

    result = await tool_cls().acall(param="value")

    assert body == []
    assert isinstance(result, _FakeToolOutput)
    assert result.is_error is True
    assert "[BLOCKED by governance policy]" in result.content


@pytest.mark.asyncio
async def test_allowed_async_tool_runs_and_records(monkeypatch: pytest.MonkeyPatch) -> None:
    body: list[str] = []
    tool_cls = _make_fake_function_tool_class(body)
    _install_fake_llamaindex(monkeypatch, tool_cls)

    interceptor = _AllowInterceptor()
    patcher = li_patch.LlamaIndexPatch(interceptor)
    assert patcher.apply() is True

    result = await tool_cls().acall(param="value")

    assert body == ["acall"]
    assert result == {"args": (), "kwargs": {"param": "value"}}
    assert interceptor.recorded == [result]


def test_unknown_verdict_blocks_under_enforce(monkeypatch: pytest.MonkeyPatch) -> None:
    body: list[str] = []
    tool_cls = _make_fake_function_tool_class(body)
    _install_fake_llamaindex(monkeypatch, tool_cls)

    class EnforcingUnknownInterceptor:
        _enforce = True

        def check_tool_start(self, **kwargs: object) -> object:
            del kwargs
            return None

    patcher = li_patch.LlamaIndexPatch(EnforcingUnknownInterceptor())
    assert patcher.apply() is True

    result = tool_cls().call(param="value")

    assert body == []
    assert isinstance(result, _FakeToolOutput)
    assert "[BLOCKED by governance policy]" in result.content


def test_pending_then_rejected_blocks_body(monkeypatch: pytest.MonkeyPatch) -> None:
    body: list[str] = []
    tool_cls = _make_fake_function_tool_class(body)
    _install_fake_llamaindex(monkeypatch, tool_cls)

    class PendingRejectInterceptor:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "pending", "reason": "needs review"}

        def wait_for_tool_approval(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "deny", "reason": "approval timeout"}

    patcher = li_patch.LlamaIndexPatch(PendingRejectInterceptor())
    assert patcher.apply() is True

    result = tool_cls().call(param="value")

    assert body == []
    assert isinstance(result, _FakeToolOutput)
    assert "[APPROVAL REJECTED]" in result.content
    assert "approval timeout" in result.content


def test_negative_control_noop_patch_would_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative control: a no-op patch must NOT block — proving the deny tests bite.

    This simulates reverting ``patched_call`` to a transparent pass-through. If
    the real patch were a no-op, ``test_denied_sync_tool_does_not_run_body``
    would observe the body running. Here we assert that the *unpatched* tool
    (no governance) runs its body even when the interceptor would deny — so the
    deny-path assertions above can only pass because the patch actively blocks.
    """
    body: list[str] = []
    tool_cls = _make_fake_function_tool_class(body)
    _install_fake_llamaindex(monkeypatch, tool_cls)

    # No patch applied: the deny interceptor has no effect; the body runs.
    result = tool_cls().call(param="value")
    assert body == ["call"]
    assert result == {"args": (), "kwargs": {"param": "value"}}
