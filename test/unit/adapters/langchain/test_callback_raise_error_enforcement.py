"""Regression test for AAASM-4658 — the ``raise_error`` swallow bypass.

``AssemblyCallbackHandler.on_tool_start`` raises ``ToolExecutionBlockedError`` on a
policy DENY, but LangChain's ``CallbackManager`` only *propagates* an exception
raised inside a callback when the handler's ``raise_error`` flag is True; with the
inherited default of False it logs the exception and runs the tool anyway. A user
who wires the handler the idiomatic LangChain way (``callbacks=[handler]``) would
then have a denied tool execute regardless — governance silently bypassed.

This exercises that real dispatch path (not a direct ``on_tool_start`` call) with
the actual LangChain ``CallbackManager``, so it fails when ``raise_error`` is False
and passes once it is True. It needs the real base class, so it is guarded by
``importorskip`` and runs only under the ``langchain-test`` dependency group:

    uv sync --group langchain-test
    .venv/bin/python -m pytest \
        test/unit/adapters/langchain/test_callback_raise_error_enforcement.py
"""

from __future__ import annotations

import pytest

pytest.importorskip("langchain_core")

from langchain_core.tools import tool  # noqa: E402

from agent_assembly.adapters.langchain import AssemblyCallbackHandler  # noqa: E402
from agent_assembly.exceptions import ToolExecutionBlockedError  # noqa: E402


class _DenyInterceptor:
    """Interceptor that denies every tool call, as an enforce-mode policy would."""

    def check_tool_start(self, **_kwargs: object) -> dict[str, str]:
        return {"status": "deny", "reason": "execute_sql denied by policy"}


def test_denied_tool_wired_as_callback_is_blocked_not_executed() -> None:
    executed: list[str] = []

    @tool
    def execute_sql(query: str) -> str:
        """Run a SQL query (must never run when policy denies it)."""
        executed.append(query)
        return "rows"

    handler = AssemblyCallbackHandler(_DenyInterceptor())

    # Attach the handler the idiomatic LangChain way rather than calling
    # ``on_tool_start`` directly — this is the path AAASM-4658 reproduces.
    with pytest.raises(ToolExecutionBlockedError):
        execute_sql.invoke({"query": "SELECT 1"}, config={"callbacks": [handler]})

    assert executed == [], "denied tool executed despite governance DENY"
