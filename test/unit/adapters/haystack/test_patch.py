"""Unit tests for the Haystack adapter patch.

These prove the adapter performs *real* governance on Haystack's tool-execution
hook (``haystack.tools.Tool.invoke``), not a no-op:

- a ``deny`` verdict blocks the underlying tool function from running and returns a
  governance string;
- an ``allow`` verdict runs the tool and records the result;
- the negative-control test (``test_real_haystack_tool_is_genuinely_governed``)
  drives a *real* ``haystack.tools.Tool`` and asserts the wrapped function never
  executed when denied — it would fail if the patch were a pass-through.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters.haystack import patch as haystack_patch


class _RecordingInterceptor:
    def check_tool_start(self, **kwargs: object) -> dict[str, str]:
        del kwargs
        return {"status": "allow"}


def _install_fake_haystack_module(monkeypatch: pytest.MonkeyPatch) -> type[Any]:
    class FakeTool:
        name = "fake_tool"

        def invoke(self, **kwargs: Any) -> dict[str, object]:
            return {"kwargs": kwargs}

    fake_tools_module = SimpleNamespace(Tool=FakeTool)

    def fake_import_module(module_name: str) -> object:
        if module_name == "haystack.tools":
            return fake_tools_module
        raise ImportError(module_name)

    monkeypatch.setattr(haystack_patch.importlib, "import_module", fake_import_module)
    return FakeTool


def test_apply_patches_invoke_and_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTool = _install_fake_haystack_module(monkeypatch)

    patcher = haystack_patch.HaystackPatch(_RecordingInterceptor())
    assert patcher.apply() is True
    first_ref = FakeTool.invoke
    assert getattr(FakeTool, haystack_patch._TOOL_PATCHED_FLAG, False) is True

    assert patcher.apply() is True
    assert FakeTool.invoke is first_ref


def test_revert_restores_invoke(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTool = _install_fake_haystack_module(monkeypatch)
    original_invoke = FakeTool.invoke

    patcher = haystack_patch.HaystackPatch(_RecordingInterceptor())
    assert patcher.apply() is True
    assert FakeTool.invoke is not original_invoke

    patcher.revert()
    assert FakeTool.invoke is original_invoke
    assert getattr(FakeTool, haystack_patch._TOOL_PATCHED_FLAG, False) is False


def test_apply_false_without_haystack(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_import_error(module_name: str) -> object:
        raise ImportError(module_name)

    monkeypatch.setattr(haystack_patch.importlib, "import_module", raise_import_error)
    assert haystack_patch._load_haystack_tool_class() is None
    assert haystack_patch.HaystackPatch(_RecordingInterceptor()).apply() is False

    monkeypatch.setattr(
        haystack_patch.importlib,
        "import_module",
        lambda name: SimpleNamespace(Tool=object()) if name == "haystack.tools" else None,
    )
    assert haystack_patch._load_haystack_tool_class() is None


def test_blocked_tool_returns_policy_string_and_skips_function(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[bool] = []

    class FakeTool:
        name = "danger_tool"

        def invoke(self, **kwargs: Any) -> dict[str, object]:
            ran.append(True)
            return {"kwargs": kwargs}

    monkeypatch.setattr(
        haystack_patch.importlib,
        "import_module",
        lambda name: (
            SimpleNamespace(Tool=FakeTool) if name == "haystack.tools" else (_ for _ in ()).throw(ImportError(name))
        ),
    )

    class BlockInterceptor:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "deny", "reason": "blocked for safety"}

    patcher = haystack_patch.HaystackPatch(BlockInterceptor())
    assert patcher.apply() is True

    result = FakeTool().invoke(param="value")

    assert isinstance(result, str)
    assert "[BLOCKED by governance policy]" in result
    assert "blocked for safety" in result
    assert ran == []  # the real tool function must NOT have executed


def test_allowed_tool_runs_and_records_result(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTool = _install_fake_haystack_module(monkeypatch)
    observed: list[object] = []

    class AllowInterceptor:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "allow"}

        def on_tool_end(self, *, output: object, **kwargs: object) -> None:
            del kwargs
            observed.append(output)

    patcher = haystack_patch.HaystackPatch(AllowInterceptor())
    assert patcher.apply() is True

    result = FakeTool().invoke(param="value")

    assert result == {"kwargs": {"param": "value"}}
    assert observed == [result]


def test_pending_tool_waits_and_allows_when_approved(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTool = _install_fake_haystack_module(monkeypatch)
    wait_calls: list[dict[str, object]] = []

    class PendingThenApproveInterceptor:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "pending", "reason": "needs approval"}

        def wait_for_tool_approval(self, **kwargs: object) -> dict[str, str]:
            wait_calls.append(dict(kwargs))
            return {"status": "allow"}

    patcher = haystack_patch.HaystackPatch(PendingThenApproveInterceptor())
    assert patcher.apply() is True

    result = FakeTool().invoke(param="value")

    assert result == {"kwargs": {"param": "value"}}
    assert len(wait_calls) == 1
    assert wait_calls[0]["timeout_seconds"] == 300


def test_pending_timeout_returns_denied_string(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTool = _install_fake_haystack_module(monkeypatch)

    class PendingTimeoutInterceptor:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "pending", "reason": "requires manual approval"}

        def wait_for_tool_approval(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "deny", "reason": "approval timeout"}

    patcher = haystack_patch.HaystackPatch(PendingTimeoutInterceptor())
    assert patcher.apply() is True

    result = FakeTool().invoke(param="value")

    assert isinstance(result, str)
    assert result.startswith("[APPROVAL REJECTED]")
    assert "approval timeout" in result


# --- AAASM-3107: unknown/None/malformed verdicts must fail closed under enforce ---


@pytest.mark.parametrize("decision", [None, "maybe", 12345, {"status": "garbage"}, {}])
def test_normalize_decision_denies_unknown_under_enforce(decision: object) -> None:
    status, reason = haystack_patch._normalize_decision(decision, enforce=True)
    assert status == "deny"
    assert reason


@pytest.mark.parametrize("decision", [None, "maybe", 12345, {"status": "garbage"}, {}])
def test_normalize_decision_allows_unknown_when_not_enforcing(decision: object) -> None:
    assert haystack_patch._normalize_decision(decision, enforce=False) == ("allow", None)


def test_normalize_decision_known_verdicts_unchanged_under_enforce() -> None:
    assert haystack_patch._normalize_decision("allow", enforce=True) == ("allow", None)
    assert haystack_patch._normalize_decision("deny", enforce=True) == ("deny", None)
    assert haystack_patch._normalize_decision("pending", enforce=True) == ("pending", None)
    assert haystack_patch._normalize_decision({"status": "deny", "reason": "x"}, enforce=True) == ("deny", "x")


def test_interceptor_enforces_reads_enforce_flag() -> None:
    assert haystack_patch._interceptor_enforces(SimpleNamespace(_enforce=True)) is True
    assert haystack_patch._interceptor_enforces(SimpleNamespace()) is False
    assert haystack_patch._interceptor_enforces(SimpleNamespace(_interceptor=SimpleNamespace(_enforce=True))) is True


def test_unknown_verdict_blocks_tool_under_enforce(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTool = _install_fake_haystack_module(monkeypatch)

    class EnforcingUnknownInterceptor:
        _enforce = True

        def check_tool_start(self, **kwargs: object) -> object:
            del kwargs
            return None

    patcher = haystack_patch.HaystackPatch(EnforcingUnknownInterceptor())
    assert patcher.apply() is True

    result = FakeTool().invoke(param="value")
    assert isinstance(result, str)
    assert "[BLOCKED by governance policy]" in result


def test_timeout_helper_branches() -> None:
    assert (
        haystack_patch._get_pending_tool_approval_timeout_seconds(
            SimpleNamespace(get_pending_tool_approval_timeout_seconds=lambda: "42")
        )
        == 42
    )
    assert (
        haystack_patch._get_pending_tool_approval_timeout_seconds(
            SimpleNamespace(pending_tool_approval_timeout_seconds=0)
        )
        == 300
    )
    assert (
        haystack_patch._get_pending_tool_approval_timeout_seconds(
            SimpleNamespace(pending_tool_approval_timeout_seconds=True)
        )
        == 300
    )
    assert (
        haystack_patch._get_pending_tool_approval_timeout_seconds(
            SimpleNamespace(pending_tool_approval_timeout_seconds=37)
        )
        == 37
    )


def test_no_handler_interceptor_defaults_to_allow() -> None:
    class NoHandlers:
        pass

    assert haystack_patch._invoke_tool_check(NoHandlers(), tool_name="x", tool_args={}) == {"status": "allow"}
    assert haystack_patch._wait_for_tool_approval(NoHandlers(), tool_name="x", timeout_seconds=1, tool_args={}) == {
        "status": "deny",
        "reason": "Approval handler is unavailable.",
    }


# --- Negative control: genuine governance over a REAL haystack.tools.Tool ---


def test_real_haystack_tool_is_genuinely_governed() -> None:
    """Drive a real ``haystack.tools.Tool`` to prove deny blocks the actual function.

    This is the no-op guard (AAASM-3528 lesson): if the patch were a pass-through the
    wrapped ``function`` would still run on deny and ``side_effects`` would be
    populated, failing this test.
    """
    haystack_tools = pytest.importorskip("haystack.tools")
    Tool = haystack_tools.Tool

    side_effects: list[tuple[int, int]] = []

    def add(a: int, b: int) -> int:
        side_effects.append((a, b))
        return a + b

    schema = {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
    }

    class DenyEverythingInterceptor:
        _enforce = True

        def __init__(self) -> None:
            self.checked: list[str] = []

        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            self.checked.append(str(kwargs.get("tool_name")))
            return {"status": "deny", "reason": "policy: arithmetic tools are blocked"}

    interceptor = DenyEverythingInterceptor()
    patcher = haystack_patch.HaystackPatch(interceptor)
    assert patcher.apply() is True
    try:
        tool = Tool(name="adder", description="adds two ints", parameters=schema, function=add)
        result = tool.invoke(a=2, b=3)

        # Governance actually fired and blocked the real tool function.
        assert interceptor.checked == ["adder"]
        assert isinstance(result, str)
        assert "[BLOCKED by governance policy]" in result
        assert "arithmetic tools are blocked" in result
        assert side_effects == []  # the real function must never have run
    finally:
        patcher.revert()

    # After revert, the same tool runs normally (proves the patch was the only gate).
    tool_after = Tool(name="adder", description="adds two ints", parameters=schema, function=add)
    assert tool_after.invoke(a=2, b=3) == 5
    assert side_effects == [(2, 3)]


def test_real_haystack_tool_allow_runs_and_records() -> None:
    """A real ``haystack.tools.Tool`` runs and its result is recorded on allow."""
    haystack_tools = pytest.importorskip("haystack.tools")
    Tool = haystack_tools.Tool

    recorded: list[object] = []

    def greet(name: str) -> str:
        return f"hello {name}"

    schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}

    class AllowAndRecordInterceptor:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "allow"}

        def record_result(self, **kwargs: object) -> None:
            recorded.append(kwargs["result"])

    patcher = haystack_patch.HaystackPatch(AllowAndRecordInterceptor())
    assert patcher.apply() is True
    try:
        tool = Tool(name="greeter", description="greets", parameters=schema, function=greet)
        result = tool.invoke(name="world")
        assert result == "hello world"
        assert recorded == ["hello world"]
    finally:
        patcher.revert()
