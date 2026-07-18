"""Regression: apply() selects the real tool-execution hook, not a vestigial one.

Pydantic AI executes tool calls through ``AbstractToolset.call_tool`` (>=0.3.0);
``Tool._run`` is only the legacy execution hook (<0.3.0). ``apply()`` used to try
``Tool._run`` FIRST and only fall back to ``call_tool``. That is correct today
because ``Tool._run`` is absent on modern versions — but a future *vestigial*
``Tool._run`` (present yet off the execution path) would satisfy the first branch,
leave ``call_tool`` unpatched, and silently make governance a dead method
(AAASM-4848). These tests exercise apply()'s hook SELECTION directly (not the
``_apply_*`` helpers in isolation) so that regression class is caught.
"""

from __future__ import annotations

from typing import Any

from agent_assembly.adapters.pydantic_ai import patch as pydantic_patch


class _Interceptor:
    def check_tool_start(self, **_kwargs: Any) -> dict[str, str]:
        return {"status": "allow"}


def test_call_tool_hook_wins_over_vestigial_tool_run(monkeypatch: Any) -> None:
    class VestigialTool:
        """A Tool whose ``_run`` exists but is NOT the execution path."""

        async def _run(self, _ctx: Any, _args: Any, **_kwargs: Any) -> str:
            return "vestigial-run"

    class ExecutionToolset:
        """The real >=0.3.0 execution hook lives on ``call_tool``."""

        async def call_tool(self, _name: Any, _args: Any, _ctx: Any, _tool: Any, **_kwargs: Any) -> str:
            return "executed"

    monkeypatch.setattr(pydantic_patch, "_load_pydantic_ai_toolset_class", lambda: ExecutionToolset)
    monkeypatch.setattr(pydantic_patch, "_load_pydantic_ai_concrete_toolset_classes", lambda _base: [])
    monkeypatch.setattr(pydantic_patch, "_load_pydantic_ai_tool_class", lambda: VestigialTool)
    monkeypatch.setattr(pydantic_patch, "_load_pydantic_ai_agent_class", lambda: None)

    patcher = pydantic_patch.PydanticAIPatch(_Interceptor())
    try:
        assert patcher.apply() is True

        # The execution hook (call_tool) is patched...
        assert vars(ExecutionToolset).get(pydantic_patch._TOOLS_PATCHED_FLAG) is True
        # ...and the vestigial Tool._run is left untouched.
        assert pydantic_patch._TOOLS_PATCHED_FLAG not in vars(VestigialTool)
        assert not hasattr(VestigialTool, pydantic_patch._ORIGINAL_TOOL_RUN)
    finally:
        pydantic_patch.set_process_agent_id(None)


def test_tool_run_is_used_as_legacy_fallback_when_no_toolset_hook(monkeypatch: Any) -> None:
    class LegacyTool:
        async def _run(self, _ctx: Any, _args: Any, **_kwargs: Any) -> str:
            return "legacy-run"

    monkeypatch.setattr(pydantic_patch, "_load_pydantic_ai_toolset_class", lambda: None)
    monkeypatch.setattr(pydantic_patch, "_load_pydantic_ai_tool_class", lambda: LegacyTool)
    monkeypatch.setattr(pydantic_patch, "_load_pydantic_ai_agent_class", lambda: None)

    patcher = pydantic_patch.PydanticAIPatch(_Interceptor())
    try:
        assert patcher.apply() is True
        assert vars(LegacyTool).get(pydantic_patch._TOOLS_PATCHED_FLAG) is True
    finally:
        pydantic_patch.set_process_agent_id(None)
