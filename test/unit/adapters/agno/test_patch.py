"""Unit tests for the Agno adapter patch.

These tests drive a *fake* ``agno.tools.function`` module so they run fast and
deterministically without importing the real framework, exercising the
allow / deny / pending / record branches and the idempotent apply+revert
contract. The real-framework governance proof (the negative control that fails
if the patch is a no-op) lives in
``test/integration/test_agno_interception_integration.py``.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters.agno import patch as agno_patch


class _FakeFunctionExecutionResult:
    """Stand-in for ``agno.tools.function.FunctionExecutionResult``."""

    def __init__(self, *, status: str, result: Any = None, error: Any = None) -> None:
        self.status = status
        self.result = result
        self.error = error


def _recording_body(sink: list[Any], return_value: Any) -> Any:
    """Return a tool body that appends its args to ``sink`` then returns ``return_value``."""

    def body(args: Any) -> Any:
        sink.append(args)
        return return_value

    return body


def _make_fake_function_call_cls(body: Any) -> type[Any]:
    """Build a fake ``FunctionCall`` whose ``execute``/``aexecute`` run ``body``."""

    class FakeFunctionCall:
        def __init__(self, name: str, arguments: dict[str, Any]) -> None:
            self.function = SimpleNamespace(name=name)
            self.arguments = arguments

        def execute(self) -> Any:
            return _FakeFunctionExecutionResult(status="success", result=body(self.arguments))

        async def aexecute(self) -> Any:
            return _FakeFunctionExecutionResult(status="success", result=body(self.arguments))

    return FakeFunctionCall


def _install_fake_agno(monkeypatch: pytest.MonkeyPatch, function_call_cls: type[Any]) -> None:
    fake_module = SimpleNamespace(
        FunctionCall=function_call_cls,
        FunctionExecutionResult=_FakeFunctionExecutionResult,
    )

    def fake_import_module(module_name: str) -> object:
        if module_name == "agno.tools.function":
            return fake_module
        raise ImportError(module_name)

    monkeypatch.setattr(agno_patch.importlib, "import_module", fake_import_module)


class _AllowInterceptor:
    def check_tool_start(self, **kwargs: object) -> dict[str, str]:
        del kwargs
        return {"status": "allow"}


def test_apply_is_idempotent_and_reverts(monkeypatch: pytest.MonkeyPatch) -> None:
    cls = _make_fake_function_call_cls(lambda args: args)
    _install_fake_agno(monkeypatch, cls)
    original_execute = cls.execute
    original_aexecute = cls.aexecute

    patcher = agno_patch.AgnoPatch(_AllowInterceptor())
    assert patcher.apply() is True
    assert cls.execute is not original_execute
    assert cls.aexecute is not original_aexecute
    first_ref = cls.execute

    # Second apply is a no-op (does not double-wrap).
    assert patcher.apply() is True
    assert cls.execute is first_ref

    patcher.revert()
    assert cls.execute is original_execute
    assert cls.aexecute is original_aexecute
    assert getattr(cls, agno_patch._TOOLS_PATCHED_FLAG, False) is False


def test_apply_false_without_agno(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_import_error(module_name: str) -> object:
        raise ImportError(module_name)

    monkeypatch.setattr(agno_patch.importlib, "import_module", raise_import_error)
    assert agno_patch._load_agno_functioncall_class() is None
    assert agno_patch.AgnoPatch(_AllowInterceptor()).apply() is False


def test_load_returns_none_for_non_type(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = SimpleNamespace(FunctionCall=object())

    def fake_import_module(module_name: str) -> object:
        if module_name == "agno.tools.function":
            return fake_module
        raise ImportError(module_name)

    monkeypatch.setattr(agno_patch.importlib, "import_module", fake_import_module)
    assert agno_patch._load_agno_functioncall_class() is None


def test_deny_blocks_body_and_returns_failure_result(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[dict[str, Any]] = []
    cls = _make_fake_function_call_cls(_recording_body(ran, "ran"))
    _install_fake_agno(monkeypatch, cls)

    class DenyInterceptor:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "deny", "reason": "blocked for safety"}

    patcher = agno_patch.AgnoPatch(DenyInterceptor())
    assert patcher.apply() is True

    result = cls("transfer", {"amount": 100}).execute()

    # The tool body must NOT have run, and the returned result is a failure.
    assert ran == []
    assert result.status == "failure"
    assert "[BLOCKED by governance policy]" in result.error
    assert "blocked for safety" in result.error


def test_allow_runs_body_and_records_result(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[dict[str, Any]] = []
    recorded: list[object] = []
    cls = _make_fake_function_call_cls(_recording_body(ran, "ok"))
    _install_fake_agno(monkeypatch, cls)

    class AllowRecording:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "allow"}

        def record_result(self, **kwargs: object) -> None:
            recorded.append(kwargs["result"])

    patcher = agno_patch.AgnoPatch(AllowRecording())
    assert patcher.apply() is True

    result = cls("lookup", {"q": "x"}).execute()

    assert ran == [{"q": "x"}]
    assert result.status == "success"
    assert result.result == "ok"
    assert len(recorded) == 1


def test_unknown_verdict_blocks_under_enforce(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[object] = []
    cls = _make_fake_function_call_cls(_recording_body(ran, "ran"))
    _install_fake_agno(monkeypatch, cls)

    class EnforcingUnknown:
        _enforce = True

        def check_tool_start(self, **kwargs: object) -> object:
            del kwargs
            return None

    patcher = agno_patch.AgnoPatch(EnforcingUnknown())
    assert patcher.apply() is True

    result = cls("anything", {}).execute()

    assert ran == []
    assert result.status == "failure"
    assert "[BLOCKED by governance policy]" in result.error


def test_pending_then_approved_runs_body(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[object] = []
    cls = _make_fake_function_call_cls(_recording_body(ran, "ran"))
    _install_fake_agno(monkeypatch, cls)

    class PendingThenApprove:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "pending", "reason": "needs approval"}

        def wait_for_tool_approval(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "allow"}

    patcher = agno_patch.AgnoPatch(PendingThenApprove())
    assert patcher.apply() is True

    result = cls("deploy", {}).execute()

    assert ran == [{}]
    assert result.status == "success"


def test_pending_then_rejected_returns_approval_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[object] = []
    cls = _make_fake_function_call_cls(_recording_body(ran, "ran"))
    _install_fake_agno(monkeypatch, cls)

    class PendingThenReject:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "pending", "reason": "needs approval"}

        def wait_for_tool_approval(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "deny", "reason": "approval timeout"}

    patcher = agno_patch.AgnoPatch(PendingThenReject())
    assert patcher.apply() is True

    result = cls("deploy", {}).execute()

    assert ran == []
    assert result.status == "failure"
    assert result.error.startswith("[APPROVAL REJECTED]")
    assert "approval timeout" in result.error


def test_async_deny_blocks_body(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[object] = []
    cls = _make_fake_function_call_cls(_recording_body(ran, "ran"))
    _install_fake_agno(monkeypatch, cls)

    class DenyInterceptor:
        _enforce = True

        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "deny", "reason": "no net"}

    patcher = agno_patch.AgnoPatch(DenyInterceptor())
    assert patcher.apply() is True

    result = asyncio.run(cls("fetch", {"url": "http://x"}).aexecute())

    assert ran == []
    assert result.status == "failure"
    assert "[BLOCKED by governance policy]" in result.error


def test_async_allow_runs_body(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[object] = []
    cls = _make_fake_function_call_cls(_recording_body(ran, "ok"))
    _install_fake_agno(monkeypatch, cls)

    patcher = agno_patch.AgnoPatch(_AllowInterceptor())
    assert patcher.apply() is True

    result = asyncio.run(cls("fetch", {"url": "http://x"}).aexecute())

    assert ran == [{"url": "http://x"}]
    assert result.status == "success"
    assert result.result == "ok"


def test_denied_result_falls_back_to_string_without_result_type(monkeypatch: pytest.MonkeyPatch) -> None:
    # When the failure-result factory is unavailable, a deny still blocks the
    # body by returning the raw block message string.
    fake_module = SimpleNamespace(FunctionExecutionResult=None)

    def fake_import_module(module_name: str) -> object:
        if module_name == "agno.tools.function":
            return fake_module
        raise ImportError(module_name)

    monkeypatch.setattr(agno_patch.importlib, "import_module", fake_import_module)
    assert agno_patch._build_denied_result("boom") == "boom"


def test_resolve_tool_name_falls_back_to_class_name() -> None:
    fc = SimpleNamespace(function=SimpleNamespace(name=None))
    assert agno_patch._resolve_tool_name(fc) == "SimpleNamespace"

    fc_named = SimpleNamespace(function=SimpleNamespace(name="my_tool"))
    assert agno_patch._resolve_tool_name(fc_named) == "my_tool"


def test_resolve_tool_args_handles_non_dict() -> None:
    assert agno_patch._resolve_tool_args(SimpleNamespace(arguments=None)) == {}
    assert agno_patch._resolve_tool_args(SimpleNamespace(arguments={"a": 1})) == {"a": 1}
