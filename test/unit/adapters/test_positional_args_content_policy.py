"""Regression: positional tool arguments must reach the content policy.

The Haystack, CrewAI, LlamaIndex and Microsoft Agent Framework adapters used to
build their governance-visible ``tool_args`` from keyword arguments only. A tool
invoked positionally (``tool.invoke("secret")``) therefore presented an empty or
partial mapping to ``check_tool_start`` — the allow/deny gate still fired on the
tool name, but argument-CONTENT policy went blind to the positional values
(AAASM-4848). Each test drives the adapter's REAL governance wrapper with a
positional secret and asserts (a) the content policy saw the secret value and
(b) a deny-on-content verdict blocked the underlying tool body from running.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_assembly.exceptions import AssemblyError

_SECRET = "sk-positional-secret-value"


class _DenyOnSecretInterceptor:
    """Content policy: deny (and record) when the sentinel secret is in the args."""

    def __init__(self) -> None:
        self.seen_args: dict[str, Any] | None = None

    def _decide(self, **kwargs: Any) -> dict[str, str]:
        args = kwargs.get("args") or {}
        self.seen_args = dict(args)
        if any(_SECRET in str(value) for value in args.values()):
            return {"status": "deny", "reason": "secret in positional argument"}
        return {"status": "allow"}

    def check_tool_start(self, **kwargs: Any) -> dict[str, str]:
        return self._decide(**kwargs)


def test_haystack_positional_arg_reaches_content_policy() -> None:
    from agent_assembly.adapters.haystack import patch as haystack_patch

    ran: list[bool] = [False]

    class FakeTool:
        name = "conformance_tool"

        def invoke(self, *_args: Any, **_kwargs: Any) -> dict[str, object]:
            ran[0] = True
            return {"ok": True}

    interceptor = _DenyOnSecretInterceptor()
    haystack_patch._apply_tool_invoke_patch(FakeTool, interceptor)

    FakeTool().invoke(_SECRET)

    assert interceptor.seen_args == {"arg0": _SECRET}
    assert ran[0] is False


def test_crewai_positional_arg_reaches_content_policy() -> None:
    from agent_assembly.adapters.crewai import patch as crewai_patch

    ran: list[bool] = [False]

    class FakeBaseTool:
        name = "conformance_tool"

        def run(self, *_args: Any, **_kwargs: Any) -> dict[str, object]:
            ran[0] = True
            return {"ok": True}

    interceptor = _DenyOnSecretInterceptor()
    crewai_patch._apply_basetool_run_patch(FakeBaseTool, interceptor)

    FakeBaseTool().run(_SECRET)

    assert interceptor.seen_args == {"arg0": _SECRET}
    assert ran[0] is False


@pytest.mark.asyncio
async def test_llamaindex_positional_arg_reaches_content_policy() -> None:
    from agent_assembly.adapters.llamaindex import patch as llamaindex_patch

    class _Meta:
        def get_name(self) -> str:
            return "conformance_tool"

    sync_ran: list[bool] = [False]
    async_ran: list[bool] = [False]

    class FakeFunctionTool:
        def __init__(self) -> None:
            self.metadata = _Meta()

        def call(self, *_args: Any, **_kwargs: Any) -> dict[str, object]:
            sync_ran[0] = True
            return {"ok": True}

        async def acall(self, *_args: Any, **_kwargs: Any) -> dict[str, object]:
            async_ran[0] = True
            return {"ok": True}

    sync_interceptor = _DenyOnSecretInterceptor()
    async_interceptor = _DenyOnSecretInterceptor()
    llamaindex_patch._apply_tool_call_patch(FakeFunctionTool, sync_interceptor)
    FakeFunctionTool().call(_SECRET)
    assert sync_interceptor.seen_args == {"arg0": _SECRET}
    assert sync_ran[0] is False

    # Re-patch acall with a fresh interceptor so the async chokepoint is covered too.
    llamaindex_patch._apply_tool_acall_patch(FakeFunctionTool, async_interceptor)
    await FakeFunctionTool().acall(_SECRET)
    assert async_interceptor.seen_args == {"arg0": _SECRET}
    assert async_ran[0] is False


@pytest.mark.asyncio
async def test_microsoft_agent_framework_positional_arguments_reach_content_policy() -> None:
    from agent_assembly.adapters.microsoft_agent_framework import patch as maf_patch

    ran: list[bool] = [False]

    class FakeFunctionTool:
        name = "conformance_tool"

        async def invoke(self, *_args: Any, **_kwargs: Any) -> str:
            ran[0] = True
            return "ok"

    interceptor = _DenyOnSecretInterceptor()
    maf_patch._apply_function_tool_invoke_patch(FakeFunctionTool, interceptor)

    # ``invoke`` called positionally: the first positional slot is ``arguments``.
    with pytest.raises(AssemblyError):
        await FakeFunctionTool().invoke({"api_key": _SECRET})

    assert interceptor.seen_args == {"api_key": _SECRET}
    assert ran[0] is False
