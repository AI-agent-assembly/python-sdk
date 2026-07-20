"""Regression tests for the shared async tool-governance flow.

These pin the fail-closed guarantee of ``run_governed_async_tool``: only an
explicit ``allow`` verdict may run the wrapped tool. A terminal ``pending``
verdict (approval round-trip that resolves to ``pending`` again) is a
non-decision and must block, mirroring the LangChain handler (AAASM-4898).
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_assembly.adapters._shared import tool_governance
from agent_assembly.exceptions import PolicyViolationError


class _TerminalPendingHandler:
    def check_tool_start(self, **kwargs: Any) -> dict[str, str]:
        del kwargs
        return {"status": "pending", "reason": "awaiting approval"}

    def wait_for_tool_approval(self, **kwargs: Any) -> dict[str, str]:
        del kwargs
        return {"status": "pending", "reason": "still pending"}


@pytest.mark.asyncio
async def test_terminal_pending_blocks_and_never_invokes_original() -> None:
    handler = _TerminalPendingHandler()
    ran: list[bool] = []

    def invoke_original() -> str:
        ran.append(True)
        return "tool-result"

    with pytest.raises(PolicyViolationError, match="rejected during approval"):
        await tool_governance.run_governed_async_tool(
            handler,
            enforce=True,
            tool_name="fake_tool",
            tool_args={"text": "hi"},
            agent_id="agent-1",
            run_id=None,
            invoke_original=invoke_original,
        )

    assert ran == []
