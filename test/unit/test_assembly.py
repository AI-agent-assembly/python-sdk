from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any

import pytest

from agent_assembly import init_assembly
from agent_assembly.core import assembly as core_assembly
from agent_assembly.exceptions import AssemblyError, ConfigurationError


@pytest.fixture(autouse=True)
def cleanup_active_context() -> None:
    active_context = core_assembly._ACTIVE_CONTEXT
    if active_context is not None and not active_context.is_shutdown:
        active_context.shutdown()
    core_assembly._ACTIVE_CONTEXT = None


def test_init_assembly_with_valid_config_returns_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_assembly, "_apply_runtime_patches", lambda **kwargs: [])
    monkeypatch.setattr(
        core_assembly,
        "_start_network_layer",
        lambda **kwargs: ("sdk-only", core_assembly._noop_shutdown),
    )

    context = init_assembly(
        gateway_url="http://localhost:8080",
        api_key="test-api-key",
        agent_id="test-agent-001",
    )

    try:
        assert context.client.agent_id == "test-agent-001"
        assert context.client.gateway_url == "http://localhost:8080"
        assert context.client.api_key == "test-api-key"
        assert context.network_mode == "sdk-only"
        assert context.patches == []
    finally:
        context.shutdown()


def test_init_assembly_with_invalid_config() -> None:
    with pytest.raises(ConfigurationError):
        init_assembly(
            gateway_url="",
            api_key="test-api-key",
            agent_id="test-agent-001",
        )

    with pytest.raises(ConfigurationError):
        init_assembly(
            gateway_url="http://localhost:8080",
            api_key="",
            agent_id="test-agent-001",
        )

    with pytest.raises(ConfigurationError):
        init_assembly(
            gateway_url="http://localhost:8080",
            api_key="test-api-key",
            mode="invalid-mode",  # type: ignore[arg-type]
        )


def test_is_installed_uses_find_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_find_spec(package: str) -> object | None:
        calls.append(package)
        if package == "installed_pkg":
            return object()
        return None

    monkeypatch.setattr(core_assembly.importlib.util, "find_spec", fake_find_spec)

    assert core_assembly._is_installed("installed_pkg") is True
    assert core_assembly._is_installed("missing_pkg") is False
    assert calls == ["installed_pkg", "missing_pkg"]


def test_is_installed_handles_find_spec_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        core_assembly.importlib.util,
        "find_spec",
        lambda package: (_ for _ in ()).throw(ValueError(package)),
    )
    assert core_assembly._is_installed("bad_pkg") is False


def test_has_agents_sdk_checks_openai_agents_module(monkeypatch: pytest.MonkeyPatch) -> None:
    checked: list[str] = []
    monkeypatch.setattr(
        core_assembly,
        "_is_installed",
        lambda package: checked.append(package) or True,
    )
    assert core_assembly._has_agents_sdk() is True
    assert checked == ["openai.agents"]


def test_build_patch_plan_langgraph_order_and_mcp_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[str] = []

    class _FakePatch:
        def __init__(self, name: str) -> None:
            self.name = name

        def apply(self) -> bool:
            return True

        def revert(self) -> None:
            return None

    monkeypatch.setattr(
        core_assembly,
        "_is_installed",
        lambda package: package
        in {"langchain", "langgraph", "crewai", "pydantic_ai", "openai", "mcp"},
    )
    monkeypatch.setattr(core_assembly, "_has_agents_sdk", lambda: True)
    monkeypatch.setattr(core_assembly, "get_active_callback_handler", lambda: object())

    monkeypatch.setattr(
        core_assembly,
        "LangChainPatch",
        lambda *args, **kwargs: created.append("langchain") or _FakePatch("langchain"),
    )
    monkeypatch.setattr(
        core_assembly,
        "LangGraphPatch",
        lambda *args, **kwargs: created.append("langgraph") or _FakePatch("langgraph"),
    )
    monkeypatch.setattr(
        core_assembly,
        "CrewAIPatch",
        lambda *args, **kwargs: created.append("crewai") or _FakePatch("crewai"),
    )
    monkeypatch.setattr(
        core_assembly,
        "PydanticAIPatch",
        lambda *args, **kwargs: created.append("pydantic_ai") or _FakePatch("pydantic_ai"),
    )
    monkeypatch.setattr(
        core_assembly,
        "OpenAIAgentsPatch",
        lambda *args, **kwargs: created.append("openai_agents") or _FakePatch("openai_agents"),
    )
    monkeypatch.setattr(
        core_assembly,
        "MCPClientPatch",
        lambda *args, **kwargs: created.append("mcp") or _FakePatch("mcp"),
    )

    patch_plan = core_assembly._build_patch_plan(client=object(), process_agent_id="agent-1")

    assert [patch.name for patch in patch_plan] == [
        "langchain",
        "langgraph",
        "crewai",
        "pydantic_ai",
        "openai_agents",
        "mcp",
    ]
    assert created[-1] == "mcp"


def test_build_patch_plan_uses_langchain_bridge_for_langgraph_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[str] = []

    class _FakePatch:
        def __init__(self, name: str) -> None:
            self.name = name

        def apply(self) -> bool:
            return True

        def revert(self) -> None:
            return None

    monkeypatch.setattr(
        core_assembly,
        "_is_installed",
        lambda package: package in {"langgraph", "crewai", "pydantic_ai", "mcp"},
    )
    monkeypatch.setattr(core_assembly, "_has_agents_sdk", lambda: False)
    monkeypatch.setattr(core_assembly, "get_active_callback_handler", lambda: None)
    monkeypatch.setattr(
        core_assembly,
        "LangChainPatch",
        lambda *args, **kwargs: created.append("langchain") or _FakePatch("langchain"),
    )
    monkeypatch.setattr(
        core_assembly,
        "LangGraphPatch",
        lambda *args, **kwargs: created.append("langgraph") or _FakePatch("langgraph"),
    )
    monkeypatch.setattr(
        core_assembly,
        "CrewAIPatch",
        lambda *args, **kwargs: created.append("crewai") or _FakePatch("crewai"),
    )
    monkeypatch.setattr(
        core_assembly,
        "PydanticAIPatch",
        lambda *args, **kwargs: created.append("pydantic_ai") or _FakePatch("pydantic_ai"),
    )
    monkeypatch.setattr(
        core_assembly,
        "MCPClientPatch",
        lambda *args, **kwargs: created.append("mcp") or _FakePatch("mcp"),
    )

    patch_plan = core_assembly._build_patch_plan(client=object(), process_agent_id="agent-1")
    assert [patch.name for patch in patch_plan] == [
        "langchain",
        "langgraph",
        "crewai",
        "pydantic_ai",
        "mcp",
    ]


def test_apply_runtime_patches_replaces_callback_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    callback_targets: list[object] = []

    class _FakePatch:
        def __init__(self, name: str, *, callback_handler: object | None = None) -> None:
            self.name = name
            self.callback_handler = callback_handler

        def apply(self) -> bool:
            callback_targets.append(self.callback_handler)
            return True

        def revert(self) -> None:
            return None

    patch_plan = [
        _FakePatch("langchain"),
        _FakePatch("crewai", callback_handler="initial"),
        _FakePatch("mcp", callback_handler="initial"),
    ]

    monkeypatch.setattr(core_assembly, "_build_patch_plan", lambda **kwargs: patch_plan)
    monkeypatch.setattr(core_assembly, "get_active_callback_handler", lambda: "runtime-callback")

    applied = core_assembly._apply_runtime_patches(client=object(), process_agent_id="agent-1")
    assert applied == patch_plan
    assert callback_targets == [None, "runtime-callback", "runtime-callback"]


def test_mode_sdk_only_skips_network_layer() -> None:
    network_mode, shutdown = core_assembly._start_network_layer(client=object(), mode="sdk-only")
    assert network_mode == "sdk-only"
    assert callable(shutdown)


def test_mode_auto_uses_proxy_when_ebpf_is_not_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core_assembly, "_platform_supports_ebpf", lambda: False)
    monkeypatch.setattr(core_assembly, "_start_mitm_proxy", lambda client: lambda: None)

    network_mode, shutdown = core_assembly._start_network_layer(client=object(), mode="auto")

    assert network_mode == "proxy"
    assert callable(shutdown)


def test_mode_auto_uses_ebpf_when_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core_assembly, "_platform_supports_ebpf", lambda: True)
    monkeypatch.setattr(core_assembly, "_start_ebpf_probes", lambda client: lambda: None)

    network_mode, shutdown = core_assembly._start_network_layer(client=object(), mode="auto")
    assert network_mode == "ebpf"
    assert callable(shutdown)


def test_mode_proxy_forces_proxy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core_assembly, "_start_mitm_proxy", lambda client: lambda: None)
    network_mode, shutdown = core_assembly._start_network_layer(client=object(), mode="proxy")
    assert network_mode == "proxy"
    assert callable(shutdown)


def test_mode_ebpf_raises_on_unsupported_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core_assembly, "_platform_supports_ebpf", lambda: False)

    with pytest.raises(ConfigurationError):
        core_assembly._start_network_layer(client=object(), mode="ebpf")


def test_context_manager_shutdown_reverts_applied_patches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class _Patch:
        def __init__(self, name: str) -> None:
            self.name = name

        def apply(self) -> bool:
            events.append(f"apply:{self.name}")
            return True

        def revert(self) -> None:
            events.append(f"revert:{self.name}")

    monkeypatch.setattr(
        core_assembly,
        "_apply_runtime_patches",
        lambda **kwargs: [_Patch("a"), _Patch("b")],
    )
    monkeypatch.setattr(
        core_assembly,
        "_start_network_layer",
        lambda **kwargs: ("sdk-only", core_assembly._noop_shutdown),
    )

    with init_assembly(
        gateway_url="http://localhost:8080",
        api_key="test-api-key",
    ) as context:
        assert context.is_shutdown is False

    assert events == ["revert:b", "revert:a"]
    assert context.is_shutdown is True


def test_init_assembly_rejects_conflicting_reinit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core_assembly, "_apply_runtime_patches", lambda **kwargs: [])
    monkeypatch.setattr(
        core_assembly,
        "_start_network_layer",
        lambda **kwargs: ("sdk-only", core_assembly._noop_shutdown),
    )

    context = init_assembly(
        gateway_url="http://localhost:8080",
        api_key="test-api-key",
        agent_id="agent-a",
    )
    try:
        with pytest.raises(ConfigurationError, match="different agent_id"):
            init_assembly(
                gateway_url="http://localhost:8080",
                api_key="test-api-key",
                agent_id="agent-b",
            )
    finally:
        context.shutdown()


def test_init_assembly_rejects_conflicting_gateway_and_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core_assembly, "_apply_runtime_patches", lambda **kwargs: [])
    monkeypatch.setattr(
        core_assembly,
        "_start_network_layer",
        lambda **kwargs: ("sdk-only", core_assembly._noop_shutdown),
    )

    context = init_assembly(
        gateway_url="http://localhost:8080",
        api_key="test-api-key",
        agent_id="agent-a",
    )
    try:
        with pytest.raises(ConfigurationError, match="different gateway_url"):
            init_assembly(
                gateway_url="http://localhost:9090",
                api_key="test-api-key",
                agent_id="agent-a",
            )
        with pytest.raises(ConfigurationError, match="different api_key"):
            init_assembly(
                gateway_url="http://localhost:8080",
                api_key="test-api-key-2",
                agent_id="agent-a",
            )
    finally:
        context.shutdown()


def test_context_shutdown_aggregates_errors() -> None:
    class _FailingPatch:
        def apply(self) -> bool:
            return True

        def revert(self) -> None:
            raise RuntimeError("patch failure")

    class _FailingClient:
        gateway_url = "http://localhost:8080"
        api_key = "test-api-key"
        agent_id = "test-agent"

        def close(self) -> None:
            raise RuntimeError("close failure")

    context = core_assembly.AssemblyContext(
        client=_FailingClient(),  # type: ignore[arg-type]
        patches=[_FailingPatch()],
        network_mode="sdk-only",
        _network_shutdown=lambda: (_ for _ in ()).throw(RuntimeError("network failure")),
    )

    with pytest.raises(AssemblyError, match="network shutdown failed"):
        context.shutdown()


def test_revert_patches_ignores_revert_failures() -> None:
    class _PatchOk:
        def apply(self) -> bool:
            return True

        def revert(self) -> None:
            return None

    class _PatchFails:
        def apply(self) -> bool:
            return True

        def revert(self) -> None:
            raise RuntimeError("boom")

    core_assembly._revert_patches([_PatchOk(), _PatchFails(), _PatchOk()])  # no raise


def test_init_assembly_is_thread_safe_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()
    apply_call_count = 0

    def fake_apply_runtime_patches(**kwargs: Any) -> list[Any]:
        nonlocal apply_call_count
        apply_call_count += 1
        started.set()
        release.wait(timeout=2)
        return []

    monkeypatch.setattr(core_assembly, "_apply_runtime_patches", fake_apply_runtime_patches)
    monkeypatch.setattr(
        core_assembly,
        "_start_network_layer",
        lambda **kwargs: ("sdk-only", core_assembly._noop_shutdown),
    )

    def initialize() -> core_assembly.AssemblyContext:
        return init_assembly(gateway_url="http://localhost:8080", api_key="test-api-key")

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_a = executor.submit(initialize)
        started.wait(timeout=2)
        future_b = executor.submit(initialize)
        release.set()

        context_a = future_a.result()
        context_b = future_b.result()

    try:
        assert context_a is context_b
        assert apply_call_count == 1
    finally:
        context_a.shutdown()
