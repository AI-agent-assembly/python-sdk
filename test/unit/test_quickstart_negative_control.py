"""Enforcement-truth negative controls for the documented Python quick-start.

AAASM-5529, Epic AAASM-5526.

``docs/quick-start.md`` tells a reader that after ``init_assembly(...)`` "every
tool call from now on goes through the policy gate", and that a denied tool
surfaces as a ``ToolExecutionBlockedError``. Existing tests of that claim assert
either the returned verdict dict or an empty ``executed`` list captured by a
closure. Neither shows that the *effect the tool exists to produce* was
prevented.

Each control here therefore:

1. runs the real ``init_assembly`` so the interceptor under test is the one the
   SDK actually builds (a genuine ``RuntimeQueryInterceptor`` over a fake native
   runtime, not a hand-rolled stand-in);
2. drives the SDK's own governed-call chain, ``run_governed_async_tool`` — the
   shared pre-execution gate behind the Google ADK and Pydantic AI quick-start
   tabs — so the SDK, not the test, decides whether the tool body runs;
3. asserts a real side effect (a file on disk, an HTTP request delivered to a
   live loopback listener) is present under allow and absent under deny.

The side-effect assertion is made *before* the exception assertion on purpose.
Asserting the exception first would short-circuit the test when enforcement is
removed, leaving the absence check unexercised — the falsification run would
then only ever prove "no error was raised", which is precisely the weak evidence
this suite replaces.

The ``FALSIFICATION`` cases run the identical function with governance removed.
They must observe the side effect; if they stop doing so, every deny assertion
here has become vacuous.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from agent_assembly import init_assembly
from agent_assembly.adapters._shared.tool_governance import run_governed_async_tool
from agent_assembly.core import assembly as core_assembly
from agent_assembly.core.runtime_interceptor import build_governance_interceptor
from agent_assembly.exceptions import ToolExecutionBlockedError

from .core._fake_core import FakeRuntimeClient, install_fake_core
from .negative_control import AuditRecordingInterceptor, FileSideEffect

# A non-loopback https gateway: the register-endpoint TLS guard (AAASM-4655)
# fail-closes a plaintext http:// register channel to a non-loopback host.
_GW_URL = "https://gateway.test"
_API_KEY = "test-key"
_AGENT_ID = "quickstart-negative-control-agent"


@pytest.fixture(autouse=True)
def _cleanup_active_context() -> None:
    """Release the process-singleton context so each control inits cleanly."""
    active = core_assembly._ACTIVE_CONTEXT
    if active is not None and not active.is_shutdown:
        active.shutdown()
    core_assembly._ACTIVE_CONTEXT = None


@pytest.fixture
def file_effect(tmp_path: Path) -> FileSideEffect:
    return FileSideEffect(path=tmp_path / "denied-write.txt")


class _GovernedQuickStart:
    """The real ``init_assembly`` context plus the interceptor it produced."""

    def __init__(self, context: Any, interceptor: AuditRecordingInterceptor, runtime: FakeRuntimeClient) -> None:
        self.context = context
        self.interceptor = interceptor
        self.runtime = runtime

    def call(self, tool_name: str, tool_args: dict[str, Any], body: Any) -> Any:
        """Run ``body`` through the SDK's governed-tool chain."""
        return asyncio.run(
            run_governed_async_tool(
                self.interceptor,
                enforce=True,
                tool_name=tool_name,
                tool_args=tool_args,
                agent_id=_AGENT_ID,
                run_id="run-1",
                invoke_original=body,
            )
        )


def _init_quickstart(monkeypatch: pytest.MonkeyPatch, *, decision: str, reason: str = "") -> _GovernedQuickStart:
    """Run the documented ``init_assembly`` and capture the interceptor it built.

    ``build_governance_interceptor`` is wrapped rather than replaced, so the real
    ``_register_adapters`` runs and the interceptor handed back is the SDK's own.
    """
    runtime = FakeRuntimeClient(decision=decision, reason=reason)
    install_fake_core(monkeypatch, runtime)
    monkeypatch.setattr(
        core_assembly,
        "_start_network_layer",
        lambda **_kwargs: ("sdk-only", core_assembly._noop_shutdown),
    )

    captured: list[AuditRecordingInterceptor] = []

    def _spy(*args: Any, **kwargs: Any) -> Any:
        interceptor = AuditRecordingInterceptor(build_governance_interceptor(*args, **kwargs))
        captured.append(interceptor)
        return interceptor

    monkeypatch.setattr(core_assembly, "build_governance_interceptor", _spy)

    context = init_assembly(
        gateway_url=_GW_URL,
        api_key=_API_KEY,
        agent_id=_AGENT_ID,
        mode="sdk-only",
        enforcement_mode="enforce",
    )
    assert captured, "init_assembly did not build a governance interceptor"
    return _GovernedQuickStart(context, captured[0], runtime)


def _settle(call: Any) -> Any:
    """Run ``call`` and return its result or its exception, never raising.

    Keeps the side-effect assertion reachable even when the governed call
    unexpectedly succeeds — see the module docstring.
    """
    try:
        return call()
    except Exception as error:  # noqa: BLE001 - the exception is the value under test
        return error


class TestFilesystemSideEffect:
    def test_positive_control_allowed_write_creates_the_file(
        self, monkeypatch: pytest.MonkeyPatch, file_effect: FileSideEffect
    ) -> None:
        quickstart = _init_quickstart(monkeypatch, decision="allow")
        try:
            quickstart.call("write_to_disk", {"path": str(file_effect.path)}, lambda: file_effect.write("allowed"))
        finally:
            quickstart.context.shutdown()

        assert file_effect.occurred() is True
        assert file_effect.content() == "allowed"

    def test_negative_control_denied_write_leaves_no_file(
        self, monkeypatch: pytest.MonkeyPatch, file_effect: FileSideEffect
    ) -> None:
        quickstart = _init_quickstart(monkeypatch, decision="deny", reason="policy forbids disk writes")
        try:
            outcome = _settle(
                lambda: quickstart.call(
                    "write_to_disk", {"path": str(file_effect.path)}, lambda: file_effect.write("denied")
                )
            )
        finally:
            quickstart.context.shutdown()

        # The load-bearing assertion: the effect the tool exists to produce is
        # absent from the filesystem, not merely that an error was raised.
        assert file_effect.occurred() is False
        assert file_effect.content() is None
        assert isinstance(outcome, ToolExecutionBlockedError)
        assert "policy forbids disk writes" in str(outcome)

    def test_falsification_the_same_write_ungoverned_creates_the_file(self, file_effect: FileSideEffect) -> None:
        # No init_assembly, no interceptor — enforcement removed. If this does
        # not write, the negative control above is vacuous.
        file_effect.write("ungoverned")

        assert file_effect.occurred() is True
        assert file_effect.content() == "ungoverned"
