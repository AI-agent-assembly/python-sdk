from __future__ import annotations

from test.unit.adapters.enforce_helpers import ENFORCE_DENY_CASES
from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters.pydantic_ai import patch as pydantic_ai_patch
from agent_assembly.exceptions import PolicyViolationError


class _RecordingInterceptor:
    async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
        del kwargs
        return {"status": "allow"}


class _ArgsModel:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def model_dump(self) -> dict[str, Any]:
        return dict(self._payload)


def _install_fake_pydantic_ai_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> type[Any]:
    class FakeTool:
        name = "fake_tool"

        async def _run(self, ctx: Any, args: Any, **kwargs: Any) -> dict[str, object]:
            return {
                "ctx": ctx,
                "args": args,
                "kwargs": kwargs,
            }

    fake_pydantic_ai_tools = SimpleNamespace(Tool=FakeTool)

    def fake_import_module(module_name: str) -> object:
        if module_name == "pydantic_ai.tools":
            return fake_pydantic_ai_tools
        raise ImportError(module_name)

    monkeypatch.setattr(pydantic_ai_patch.importlib, "import_module", fake_import_module)
    return FakeTool


@pytest.mark.asyncio
async def test_apply_patches_tool_run_and_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTool = _install_fake_pydantic_ai_modules(monkeypatch)

    patcher = pydantic_ai_patch.PydanticAIPatch(_RecordingInterceptor())
    assert patcher.apply() is True
    first_run_ref = FakeTool._run

    assert getattr(FakeTool, pydantic_ai_patch._TOOLS_PATCHED_FLAG, False) is True

    assert patcher.apply() is True
    assert FakeTool._run is first_run_ref


def test_revert_restores_tool_run_and_clears_process_agent_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeTool = _install_fake_pydantic_ai_modules(monkeypatch)
    original_run = FakeTool._run
    pydantic_ai_patch.set_process_agent_id("agent-before-revert")

    patcher = pydantic_ai_patch.PydanticAIPatch(_RecordingInterceptor())
    assert patcher.apply() is True
    assert FakeTool._run is not original_run

    patcher.revert()
    assert FakeTool._run is original_run
    assert getattr(FakeTool, pydantic_ai_patch._TOOLS_PATCHED_FLAG, False) is False
    assert pydantic_ai_patch._get_process_agent_id() is None


def test_loader_edge_cases_and_apply_false_without_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_import_error(module_name: str) -> object:
        raise ImportError(module_name)

    monkeypatch.setattr(pydantic_ai_patch.importlib, "import_module", raise_import_error)
    assert pydantic_ai_patch._load_pydantic_ai_tool_class() is None
    assert pydantic_ai_patch.PydanticAIPatch(_RecordingInterceptor()).apply() is False

    fake_pydantic_ai_tools = SimpleNamespace(Tool=object())

    def return_non_type(module_name: str) -> object:
        if module_name == "pydantic_ai.tools":
            return fake_pydantic_ai_tools
        raise ImportError(module_name)

    monkeypatch.setattr(pydantic_ai_patch.importlib, "import_module", return_non_type)
    assert pydantic_ai_patch._load_pydantic_ai_tool_class() is None


def test_helper_branches_for_agent_id_timeout_and_serialization() -> None:
    class TimeoutProvider:
        def get_pending_tool_approval_timeout_seconds(self) -> str:
            return "42"

    assert pydantic_ai_patch._get_pending_tool_approval_timeout_seconds(TimeoutProvider()) == 42
    assert (
        pydantic_ai_patch._get_pending_tool_approval_timeout_seconds(
            SimpleNamespace(pending_tool_approval_timeout_seconds=0)
        )
        == 300
    )
    assert (
        pydantic_ai_patch._get_pending_tool_approval_timeout_seconds(
            SimpleNamespace(pending_tool_approval_timeout_seconds=True)
        )
        == 300
    )

    assert pydantic_ai_patch._normalize_decision("deny") == ("deny", None)
    assert pydantic_ai_patch._normalize_decision("pending") == ("pending", None)
    assert pydantic_ai_patch._normalize_decision("allow") == ("allow", None)
    assert pydantic_ai_patch._normalize_decision(12345) == ("allow", None)

    pydantic_ai_patch.set_process_agent_id("process-agent")
    ctx_with_deps = SimpleNamespace(deps=SimpleNamespace(assembly_agent_id="deps-agent"), run_id=123)
    ctx_without_deps = SimpleNamespace(deps=SimpleNamespace(), run_id=None)

    assert pydantic_ai_patch._resolve_agent_id(ctx_with_deps) == "deps-agent"
    assert pydantic_ai_patch._resolve_agent_id(ctx_without_deps) == "process-agent"
    assert pydantic_ai_patch._resolve_run_id(ctx_with_deps) == "123"
    assert pydantic_ai_patch._resolve_run_id(ctx_without_deps) is None

    model_args = _ArgsModel({"x": 1, "y": 2})
    assert pydantic_ai_patch._serialize_tool_args(model_args) == {"x": 1, "y": 2}
    assert pydantic_ai_patch._serialize_tool_args({"a": 1}) == {"a": 1}
    assert pydantic_ai_patch._serialize_tool_args(99) == {"value": "99"}

    pydantic_ai_patch.set_process_agent_id(None)


@pytest.mark.asyncio
async def test_denied_tool_raises_policy_violation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTool = _install_fake_pydantic_ai_modules(monkeypatch)

    class BlockInterceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "deny", "reason": "blocked for safety"}

    patcher = pydantic_ai_patch.PydanticAIPatch(BlockInterceptor())
    assert patcher.apply() is True

    tool = FakeTool()
    ctx = SimpleNamespace(deps=SimpleNamespace(assembly_agent_id="agent-a"), run_id="run-1")
    args = _ArgsModel({"topic": "finance"})

    with pytest.raises(PolicyViolationError, match="blocked by governance policy: blocked for safety"):
        await tool._run(ctx, args)


@pytest.mark.asyncio
async def test_pending_then_approved_runs_and_records_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeTool = _install_fake_pydantic_ai_modules(monkeypatch)
    wait_calls: list[dict[str, object]] = []
    recorded_results: list[dict[str, object]] = []

    class PendingThenApproveInterceptor:
        pending_tool_approval_timeout_seconds = 25

        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "pending", "reason": "needs approval"}

        async def wait_for_tool_approval(self, **kwargs: object) -> dict[str, str]:
            wait_calls.append(dict(kwargs))
            return {"status": "allow"}

        async def record_result(self, **kwargs: object) -> None:
            recorded_results.append(dict(kwargs))

    patcher = pydantic_ai_patch.PydanticAIPatch(PendingThenApproveInterceptor())
    assert patcher.apply() is True

    tool = FakeTool()
    ctx = SimpleNamespace(deps=SimpleNamespace(assembly_agent_id="agent-b"), run_id="run-2")
    result = await tool._run(ctx, _ArgsModel({"q": "hello"}), trace="yes")

    assert result["kwargs"] == {"trace": "yes"}
    assert len(wait_calls) == 1
    assert wait_calls[0]["timeout_seconds"] == 25
    assert len(recorded_results) == 1
    assert recorded_results[0]["tool_name"] == "fake_tool"
    assert recorded_results[0]["agent_id"] == "agent-b"


@pytest.mark.asyncio
async def test_pending_then_rejected_raises_policy_violation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeTool = _install_fake_pydantic_ai_modules(monkeypatch)

    class PendingThenRejectInterceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "pending", "reason": "requires approval"}

        async def wait_for_tool_approval(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "deny", "reason": "approval rejected"}

    patcher = pydantic_ai_patch.PydanticAIPatch(PendingThenRejectInterceptor())
    assert patcher.apply() is True

    tool = FakeTool()
    ctx = SimpleNamespace(deps=SimpleNamespace(assembly_agent_id="agent-c"), run_id="run-3")
    args = _ArgsModel({"q": "secret"})

    with pytest.raises(PolicyViolationError, match="rejected during approval: approval rejected"):
        await tool._run(ctx, args)


@pytest.mark.asyncio
async def test_result_recording_truncates_to_2000_chars(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeTool:
        name = "truncate_tool"

        async def _run(self, ctx: Any, args: Any, **kwargs: Any) -> str:
            del ctx, args, kwargs
            return "x" * 2500

    fake_pydantic_ai_tools = SimpleNamespace(Tool=FakeTool)

    def fake_import_module(module_name: str) -> object:
        if module_name == "pydantic_ai.tools":
            return fake_pydantic_ai_tools
        raise ImportError(module_name)

    monkeypatch.setattr(pydantic_ai_patch.importlib, "import_module", fake_import_module)

    observed: list[str] = []

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "allow"}

        async def record_result(self, **kwargs: object) -> None:
            observed.append(str(kwargs["result"]))

    patcher = pydantic_ai_patch.PydanticAIPatch(Interceptor())
    assert patcher.apply() is True

    tool = FakeTool()
    ctx = SimpleNamespace(deps=SimpleNamespace(assembly_agent_id="agent-d"), run_id="run-4")
    result = await tool._run(ctx, _ArgsModel({"q": "long"}))

    assert isinstance(result, str)
    assert len(result) == 2500
    assert len(observed) == 1
    assert len(observed[0]) == 2000


@pytest.mark.asyncio
async def test_assembly_model_wrapper_scans_and_forwards_request() -> None:
    class FakeModel:
        async def request(self, *args: object, **kwargs: object) -> str:
            del kwargs
            return f"forwarded:{args[0]}"

    scanned_prompts: list[list[str]] = []

    class Interceptor:
        async def on_llm_start_scan(self, **kwargs: object) -> None:
            prompts = kwargs.get("prompts", [])
            if isinstance(prompts, list):
                scanned_prompts.append([str(item) for item in prompts])

    wrapper = pydantic_ai_patch.AssemblyModelWrapper(FakeModel(), Interceptor())
    result = await wrapper.request("hello")

    assert result == "forwarded:hello"
    assert scanned_prompts == [["hello"]]


@pytest.mark.asyncio
async def test_assembly_model_wrapper_passthrough_attrs() -> None:
    class FakeModel:
        model_name = "demo-model"

        def request(self, *args: object, **kwargs: object) -> str:
            del args, kwargs
            return "ok"

    wrapper = pydantic_ai_patch.AssemblyModelWrapper(FakeModel(), object())
    assert wrapper.model_name == "demo-model"
    result = await wrapper.request("ignored")
    assert result == "ok"


@pytest.mark.asyncio
async def test_fallback_and_non_awaitable_branches_for_async_helpers() -> None:
    class NoHandlers:
        pass

    pydantic_ai_patch.set_process_agent_id(None)
    assert pydantic_ai_patch._get_process_agent_id() is None

    fallback_check = await pydantic_ai_patch._invoke_async_tool_check(
        NoHandlers(),
        tool_name="x",
        tool_args={},
        agent_id=None,
        run_id=None,
    )
    assert fallback_check == {"status": "allow"}

    fallback_wait = await pydantic_ai_patch._wait_for_async_tool_approval(
        NoHandlers(),
        tool_name="x",
        timeout_seconds=1,
        tool_args={},
        agent_id=None,
        run_id=None,
    )
    assert fallback_wait == {"status": "deny", "reason": "Approval handler is unavailable."}

    assert (
        pydantic_ai_patch._get_pending_tool_approval_timeout_seconds(
            SimpleNamespace(pending_tool_approval_timeout_seconds="NaN")
        )
        == 300
    )

    class SyncInterceptor:
        def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "allow"}

        def wait_for_tool_approval(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "allow"}

    sync_check = await pydantic_ai_patch._invoke_async_tool_check(
        SyncInterceptor(),
        tool_name="x",
        tool_args={},
        agent_id=None,
        run_id=None,
    )
    assert sync_check == {"status": "allow"}

    sync_wait = await pydantic_ai_patch._wait_for_async_tool_approval(
        SyncInterceptor(),
        tool_name="x",
        timeout_seconds=2,
        tool_args={},
        agent_id=None,
        run_id=None,
    )
    assert sync_wait == {"status": "allow"}

    observed_outputs: list[str] = []

    class ToolEndOnlyInterceptor:
        async def on_tool_end(self, **kwargs: object) -> None:
            observed_outputs.append(str(kwargs["output"]))

    await pydantic_ai_patch._record_async_tool_result(
        ToolEndOnlyInterceptor(),
        tool_name="fallback",
        result="result-value",
        agent_id="agent-z",
        run_id="run-z",
    )
    assert observed_outputs == ["result-value"]


def _install_fake_pydantic_ai_v030_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> type[Any]:
    """Model Pydantic AI >=0.3.0: ``Tool`` has no ``_run`` and tool execution
    routes through ``AbstractToolset.call_tool(self, name, tool_args, ctx, tool)``.
    """

    class FakeTool:
        # Note: no `_run` method — mirrors the >=0.3.0 restructure.
        name = "fake_tool"

    class FakeAbstractToolset:
        async def call_tool(self, name: Any, tool_args: Any, ctx: Any, tool: Any) -> dict[str, object]:
            return {"name": name, "tool_args": tool_args, "ctx": ctx, "tool": tool}

    fake_tools_module = SimpleNamespace(Tool=FakeTool)
    fake_toolsets_module = SimpleNamespace(AbstractToolset=FakeAbstractToolset)

    def fake_import_module(module_name: str) -> object:
        if module_name == "pydantic_ai.tools":
            return fake_tools_module
        if module_name == "pydantic_ai.toolsets":
            return fake_toolsets_module
        raise ImportError(module_name)

    monkeypatch.setattr(pydantic_ai_patch.importlib, "import_module", fake_import_module)
    return FakeAbstractToolset


@pytest.mark.asyncio
async def test_apply_patches_toolset_call_tool_for_v030(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeAbstractToolset = _install_fake_pydantic_ai_v030_modules(monkeypatch)

    patcher = pydantic_ai_patch.PydanticAIPatch(_RecordingInterceptor())
    assert patcher.apply() is True
    assert getattr(FakeAbstractToolset, pydantic_ai_patch._TOOLS_PATCHED_FLAG, False) is True

    first_ref = FakeAbstractToolset.call_tool
    # Re-applying is idempotent.
    assert patcher.apply() is True
    assert FakeAbstractToolset.call_tool is first_ref


@pytest.mark.asyncio
async def test_v030_toolset_allow_flow_runs_and_records(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeAbstractToolset = _install_fake_pydantic_ai_v030_modules(monkeypatch)

    recorded: list[dict[str, object]] = []

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "allow"}

        async def record_result(self, **kwargs: object) -> None:
            recorded.append(dict(kwargs))

    patcher = pydantic_ai_patch.PydanticAIPatch(Interceptor())
    assert patcher.apply() is True

    toolset = FakeAbstractToolset()
    ctx = SimpleNamespace(deps=SimpleNamespace(assembly_agent_id="agent-x"), run_id="run-x")
    result = await toolset.call_tool("fake_tool", {"q": "hi"}, ctx, object())

    assert result["name"] == "fake_tool"
    assert len(recorded) == 1
    assert recorded[0]["tool_name"] == "fake_tool"
    assert recorded[0]["agent_id"] == "agent-x"


@pytest.mark.asyncio
async def test_v030_toolset_deny_flow_raises_policy_violation(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeAbstractToolset = _install_fake_pydantic_ai_v030_modules(monkeypatch)

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "deny", "reason": "blocked v030"}

    patcher = pydantic_ai_patch.PydanticAIPatch(Interceptor())
    assert patcher.apply() is True

    toolset = FakeAbstractToolset()
    ctx = SimpleNamespace(deps=SimpleNamespace(assembly_agent_id="agent-x"), run_id="run-x")
    with pytest.raises(PolicyViolationError, match="blocked by governance policy: blocked v030"):
        await toolset.call_tool("fake_tool", {"q": "hi"}, ctx, object())


def test_v030_revert_restores_toolset_call_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeAbstractToolset = _install_fake_pydantic_ai_v030_modules(monkeypatch)
    original_call_tool = FakeAbstractToolset.call_tool

    patcher = pydantic_ai_patch.PydanticAIPatch(_RecordingInterceptor())
    assert patcher.apply() is True
    assert FakeAbstractToolset.call_tool is not original_call_tool

    patcher.revert()
    assert FakeAbstractToolset.call_tool is original_call_tool
    assert getattr(FakeAbstractToolset, pydantic_ai_patch._TOOLS_PATCHED_FLAG, False) is False


def _install_fake_pydantic_ai_function_toolset_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[type[Any], type[Any]]:
    """Model the >=0.3.0 shadowing bug: ``FunctionToolset`` subclasses
    ``AbstractToolset`` and overrides ``call_tool`` WITHOUT calling ``super()``.

    A patch on ``AbstractToolset.call_tool`` is shadowed for function tools, so
    the concrete class must be discovered and patched directly. Returns the
    ``(AbstractToolset, FunctionToolset)`` fakes.
    """

    class FakeTool:
        name = "fake_tool"  # no `_run` — mirrors the >=0.3.0 restructure

    class FakeAbstractToolset:
        async def call_tool(self, name: Any, tool_args: Any, ctx: Any, tool: Any) -> dict[str, object]:
            return {"src": "abstract", "name": name, "tool_args": tool_args, "ctx": ctx, "tool": tool}

    class FakeFunctionToolset(FakeAbstractToolset):
        # Overrides call_tool WITHOUT super() — the shadowing that hides the
        # base-class patch from function tools.
        async def call_tool(self, name: Any, tool_args: Any, ctx: Any, tool: Any) -> dict[str, object]:
            return {"src": "function", "name": name, "tool_args": tool_args, "ctx": ctx, "tool": tool}

    fake_tools_module = SimpleNamespace(Tool=FakeTool)
    fake_toolsets_module = SimpleNamespace(AbstractToolset=FakeAbstractToolset)
    fake_function_module = SimpleNamespace(FunctionToolset=FakeFunctionToolset)

    def fake_import_module(module_name: str) -> object:
        if module_name == "pydantic_ai.tools":
            return fake_tools_module
        if module_name == "pydantic_ai.toolsets":
            return fake_toolsets_module
        if module_name == "pydantic_ai.toolsets.function":
            return fake_function_module
        raise ImportError(module_name)

    monkeypatch.setattr(pydantic_ai_patch.importlib, "import_module", fake_import_module)
    return FakeAbstractToolset, FakeFunctionToolset


def test_concrete_toolset_discovery_finds_function_toolset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAbstractToolset, FakeFunctionToolset = _install_fake_pydantic_ai_function_toolset_modules(monkeypatch)

    discovered = pydantic_ai_patch._load_pydantic_ai_concrete_toolset_classes(FakeAbstractToolset)
    assert FakeFunctionToolset in discovered
    # The abstract base itself is never returned as a "concrete overrider".
    assert FakeAbstractToolset not in discovered


@pytest.mark.asyncio
async def test_apply_patches_both_base_and_concrete_function_toolset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAbstractToolset, FakeFunctionToolset = _install_fake_pydantic_ai_function_toolset_modules(monkeypatch)

    patcher = pydantic_ai_patch.PydanticAIPatch(_RecordingInterceptor())
    assert patcher.apply() is True

    # Both classes carry their OWN patched flag — a patched base must not mask
    # the concrete subclass.
    assert vars(FakeAbstractToolset).get(pydantic_ai_patch._TOOLS_PATCHED_FLAG, False) is True
    assert vars(FakeFunctionToolset).get(pydantic_ai_patch._TOOLS_PATCHED_FLAG, False) is True


@pytest.mark.asyncio
async def test_denied_tool_raises_when_invoked_via_concrete_call_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, FakeFunctionToolset = _install_fake_pydantic_ai_function_toolset_modules(monkeypatch)

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "deny", "reason": "blocked function tool"}

    patcher = pydantic_ai_patch.PydanticAIPatch(Interceptor())
    assert patcher.apply() is True

    toolset = FakeFunctionToolset()
    ctx = SimpleNamespace(deps=SimpleNamespace(assembly_agent_id="agent-fn"), run_id="run-fn")

    # Governance fires on the concrete override, not just the (shadowed) base.
    with pytest.raises(PolicyViolationError, match="blocked by governance policy: blocked function tool"):
        await toolset.call_tool("fake_tool", {"q": "secret"}, ctx, object())


@pytest.mark.asyncio
async def test_revert_restores_concrete_and_base_call_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAbstractToolset, FakeFunctionToolset = _install_fake_pydantic_ai_function_toolset_modules(monkeypatch)
    original_base = FakeAbstractToolset.call_tool
    original_concrete = FakeFunctionToolset.call_tool

    patcher = pydantic_ai_patch.PydanticAIPatch(_RecordingInterceptor())
    assert patcher.apply() is True
    assert FakeAbstractToolset.call_tool is not original_base
    assert FakeFunctionToolset.call_tool is not original_concrete

    patcher.revert()
    assert FakeAbstractToolset.call_tool is original_base
    assert FakeFunctionToolset.call_tool is original_concrete
    assert vars(FakeAbstractToolset).get(pydantic_ai_patch._TOOLS_PATCHED_FLAG, False) is False
    assert vars(FakeFunctionToolset).get(pydantic_ai_patch._TOOLS_PATCHED_FLAG, False) is False

    # Revert is idempotent.
    patcher.revert()
    assert FakeFunctionToolset.call_tool is original_concrete


def test_concrete_toolset_discovery_fail_soft_without_pydantic_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_import_error(module_name: str) -> object:
        raise ImportError(module_name)

    monkeypatch.setattr(pydantic_ai_patch.importlib, "import_module", raise_import_error)

    class FakeBase:
        pass

    assert pydantic_ai_patch._load_pydantic_ai_concrete_toolset_classes(FakeBase) == []


def test_apply_false_when_no_known_tool_hook_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pydantic AI present but exposing neither ``Tool._run`` nor
    ``AbstractToolset.call_tool`` must no-op (return False), never raise.
    """

    class FakeTool:
        name = "fake_tool"  # no `_run`

    class FakeAbstractToolset:
        pass  # no `call_tool`

    def fake_import_module(module_name: str) -> object:
        if module_name == "pydantic_ai.tools":
            return SimpleNamespace(Tool=FakeTool)
        if module_name == "pydantic_ai.toolsets":
            return SimpleNamespace(AbstractToolset=FakeAbstractToolset)
        raise ImportError(module_name)

    monkeypatch.setattr(pydantic_ai_patch.importlib, "import_module", fake_import_module)

    patcher = pydantic_ai_patch.PydanticAIPatch(_RecordingInterceptor())
    assert patcher.apply() is False
    assert pydantic_ai_patch._get_process_agent_id() is None


# --- AAASM-4734: fail closed on unrecognized verdict / missing interceptor ---


@pytest.mark.asyncio
@pytest.mark.parametrize("interceptor_factory", ENFORCE_DENY_CASES)
async def test_denies_under_enforce(
    monkeypatch: pytest.MonkeyPatch,
    interceptor_factory: type,
) -> None:
    FakeTool = _install_fake_pydantic_ai_modules(monkeypatch)

    patcher = pydantic_ai_patch.PydanticAIPatch(interceptor_factory())
    assert patcher.apply() is True

    tool = FakeTool()
    ctx = SimpleNamespace(deps=SimpleNamespace(assembly_agent_id="agent-a"), run_id="run-1")
    args = _ArgsModel({"topic": "finance"})
    with pytest.raises(PolicyViolationError):
        await tool._run(ctx, args)
