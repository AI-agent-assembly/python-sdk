from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_assembly.adapters.mcp import patch as mcp_patch
from agent_assembly.exceptions import MCPToolBlockedError


class _ArgsMapping(dict[str, object]):
    pass


def _install_fake_mcp_module(monkeypatch: pytest.MonkeyPatch) -> type[Any]:
    class FakeClientSession:
        async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
            return {
                "name": name,
                "arguments": arguments or {},
            }

    fake_mcp_module = SimpleNamespace(ClientSession=FakeClientSession)

    def fake_import_module(module_name: str) -> object:
        if module_name == "mcp":
            return fake_mcp_module
        raise ImportError(module_name)

    monkeypatch.setattr(mcp_patch.importlib, "import_module", fake_import_module)
    return FakeClientSession


@pytest.mark.asyncio
async def test_apply_patches_clientsession_call_tool_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeClientSession = _install_fake_mcp_module(monkeypatch)

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "allow"}

    patcher = mcp_patch.MCPClientPatch(Interceptor(), process_agent_id="agent-1")
    assert patcher.apply() is True
    first_call_ref = FakeClientSession.call_tool

    assert getattr(FakeClientSession, mcp_patch._PATCHED_FLAG, False) is True
    assert mcp_patch._get_process_agent_id() == "agent-1"

    assert patcher.apply() is True
    assert FakeClientSession.call_tool is first_call_ref


def test_revert_restores_clientsession_call_tool_and_clears_process_agent_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeClientSession = _install_fake_mcp_module(monkeypatch)
    original_call_tool = FakeClientSession.call_tool
    mcp_patch.set_process_agent_id("agent-before-revert")

    patcher = mcp_patch.MCPClientPatch(object())
    assert patcher.apply() is True
    assert FakeClientSession.call_tool is not original_call_tool

    patcher.revert()
    assert FakeClientSession.call_tool is original_call_tool
    assert getattr(FakeClientSession, mcp_patch._PATCHED_FLAG, False) is False
    assert mcp_patch._get_process_agent_id() is None


def test_loaders_and_apply_false_when_mcp_clientsession_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mcp_patch.importlib,
        "import_module",
        lambda _: (_ for _ in ()).throw(ImportError("mcp")),
    )
    assert mcp_patch._load_mcp_client_session_class() is None
    assert mcp_patch.MCPClientPatch(callback_handler=object()).apply() is False

    fake_mcp_module = SimpleNamespace(ClientSession=object())
    monkeypatch.setattr(
        mcp_patch.importlib,
        "import_module",
        lambda name: fake_mcp_module if name == "mcp" else (_ for _ in ()).throw(ImportError(name)),
    )
    assert mcp_patch._load_mcp_client_session_class() is None


def test_server_identifier_extraction_handles_transport_variants() -> None:
    sse_session = SimpleNamespace(_server_url="https://sse.mcp.test")
    stdio_session = SimpleNamespace(_server_name="stdio-server")
    ws_session = SimpleNamespace(_ws_url="wss://ws.mcp.test")
    transport_session = SimpleNamespace(_transport=SimpleNamespace(server_name="transport-server"))
    unknown_session = SimpleNamespace()

    assert mcp_patch._get_server_identifier(sse_session) == "https://sse.mcp.test"
    assert mcp_patch._get_server_identifier(stdio_session) == "stdio-server"
    assert mcp_patch._get_server_identifier(ws_session) == "wss://ws.mcp.test"
    assert mcp_patch._get_server_identifier(transport_session) == "transport-server"
    assert mcp_patch._get_server_identifier(unknown_session) == "mcp-unknown"


@pytest.mark.asyncio
async def test_denied_tool_raises_mcp_tool_blocked_error_with_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeClientSession = _install_fake_mcp_module(monkeypatch)

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            assert kwargs["tool_name"] == "blocked_tool"
            return {"status": "deny", "reason": "policy block"}

    patcher = mcp_patch.MCPClientPatch(Interceptor(), process_agent_id="agent-7")
    assert patcher.apply() is True

    session = FakeClientSession()
    session._server_name = "stdlib-server"  # type: ignore[attr-defined]
    with pytest.raises(
        MCPToolBlockedError,
        match="blocked by governance policy: policy block",
    ) as captured:
        await session.call_tool("blocked_tool", {"q": "secret"})

    error = captured.value
    assert error.tool_name == "blocked_tool"
    assert error.server == "stdlib-server"


@pytest.mark.asyncio
async def test_pending_then_approved_runs_original_and_records_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeClientSession = _install_fake_mcp_module(monkeypatch)
    wait_calls: list[dict[str, object]] = []
    recorded_results: list[dict[str, object]] = []

    class Interceptor:
        pending_tool_approval_timeout_seconds = 17

        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "pending", "reason": "approval required"}

        async def wait_for_tool_approval(self, **kwargs: object) -> dict[str, str]:
            wait_calls.append(dict(kwargs))
            return {"status": "allow"}

        async def record_result(self, **kwargs: object) -> None:
            recorded_results.append(dict(kwargs))

    patcher = mcp_patch.MCPClientPatch(Interceptor(), process_agent_id="agent-9")
    assert patcher.apply() is True

    session = FakeClientSession()
    session._server_url = "https://api.mcp.test"  # type: ignore[attr-defined]
    result = await session.call_tool("search", _ArgsMapping({"q": "hello"}))

    assert result["name"] == "search"
    assert len(wait_calls) == 1
    assert wait_calls[0]["timeout_seconds"] == 17
    assert len(recorded_results) == 1
    assert recorded_results[0]["tool_name"] == "search"
    assert recorded_results[0]["agent_id"] == "agent-9"
    assert recorded_results[0]["server"] == "https://api.mcp.test"


@pytest.mark.asyncio
async def test_pending_then_rejected_raises_mcp_tool_blocked_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeClientSession = _install_fake_mcp_module(monkeypatch)

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "pending", "reason": "approval required"}

        async def wait_for_tool_approval(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "deny", "reason": "approval rejected"}

    patcher = mcp_patch.MCPClientPatch(Interceptor())
    assert patcher.apply() is True

    session = FakeClientSession()
    session._ws_url = "wss://tools.mcp.test"  # type: ignore[attr-defined]
    with pytest.raises(
        MCPToolBlockedError,
        match="rejected during approval: approval rejected",
    ) as captured:
        await session.call_tool("deploy", {"service": "api"})

    assert captured.value.tool_name == "deploy"
    assert captured.value.server == "wss://tools.mcp.test"


@pytest.mark.asyncio
async def test_result_recording_truncates_to_2000_chars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClientSession:
        async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
            del name, arguments
            return "x" * 2500

    fake_mcp_module = SimpleNamespace(ClientSession=FakeClientSession)
    monkeypatch.setattr(
        mcp_patch.importlib,
        "import_module",
        lambda name: fake_mcp_module if name == "mcp" else (_ for _ in ()).throw(ImportError(name)),
    )

    observed_results: list[str] = []

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            del kwargs
            return {"status": "allow"}

        async def record_result(self, **kwargs: object) -> None:
            observed_results.append(str(kwargs["result"]))

    patcher = mcp_patch.MCPClientPatch(Interceptor())
    assert patcher.apply() is True

    result = await FakeClientSession().call_tool("long-output", {"debug": True})

    assert isinstance(result, str)
    assert len(result) == 2500
    assert len(observed_results) == 1
    assert len(observed_results[0]) == 2000


@pytest.mark.asyncio
async def test_callback_wrapper_with_interceptor_is_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeClientSession = _install_fake_mcp_module(monkeypatch)
    seen: list[str] = []

    class Interceptor:
        async def check_tool_start(self, **kwargs: object) -> dict[str, str]:
            seen.append(str(kwargs.get("tool_name")))
            return {"status": "allow"}

    wrapper = SimpleNamespace(_interceptor=Interceptor())
    patcher = mcp_patch.MCPClientPatch(wrapper)
    assert patcher.apply() is True

    result = await FakeClientSession().call_tool(name="from-wrapper", arguments={"ok": True})
    assert result["name"] == "from-wrapper"
    assert seen == ["from-wrapper"]
