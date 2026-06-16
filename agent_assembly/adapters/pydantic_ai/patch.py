"""Pydantic AI patch module."""

from __future__ import annotations

import importlib as importlib
import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from functools import wraps
from typing import Any, Literal

from agent_assembly.adapters.crewai.patch import (
    _get_pending_tool_approval_timeout_seconds as _resolve_pending_timeout_seconds,
)
from agent_assembly.adapters.crewai.patch import (
    _normalize_decision as _normalize_governance_decision,
)
from agent_assembly.core.spawn import _SPAWN_CTX, SpawnContext, spawn_context_scope

_ORIGINAL_TOOL_RUN = "_agent_assembly_original_pydantic_ai_tool_run"
_ORIGINAL_TOOLSET_CALL_TOOL = "_agent_assembly_original_pydantic_ai_toolset_call_tool"
_TOOLS_PATCHED_FLAG = "_agent_assembly_pydantic_ai_tools_patched"
_ORIGINAL_AGENT_RUN = "_agent_assembly_original_pydantic_ai_agent_run"
_ORIGINAL_AGENT_RUN_SYNC = "_agent_assembly_original_pydantic_ai_agent_run_sync"
_AGENT_PATCHED_FLAG = "_agent_assembly_pydantic_ai_agent_patched"
_PROCESS_AGENT_ID: str | None = None
_MAX_AUDIT_RESULT_CHARS = 2000


@dataclass(slots=True)
class PydanticAIPatch:
    """Applies Pydantic AI runtime monkey-patching hooks."""

    callback_handler: Any
    process_agent_id: str | None = None

    def apply(self) -> bool:
        """Apply patch wiring and return whether a tool hook was installed.

        Detects the tool-execution hook across Pydantic AI versions: the
        ``Tool._run`` hook on <0.3.0 and the ``AbstractToolset.call_tool``
        hook on >=0.3.0. When neither hook point exists, this is a no-op that
        returns ``False`` instead of raising ``AttributeError``.

        On >=0.3.0 the abstract base patch is shadowed by concrete toolsets
        (e.g. ``FunctionToolset``) that override ``call_tool`` without calling
        ``super().call_tool(...)``. Such concrete classes are patched directly
        in addition to the base so function-tool governance still fires.
        """
        set_process_agent_id(self.process_agent_id)

        tool_hooked = False
        tool_cls = _load_pydantic_ai_tool_class()
        if tool_cls is not None:
            tool_hooked = _apply_tool_run_patch(tool_cls, self.callback_handler)
        if not tool_hooked:
            toolset_cls = _load_pydantic_ai_toolset_class()
            if toolset_cls is not None:
                tool_hooked = _apply_toolset_call_tool_patch(toolset_cls, self.callback_handler)
                for concrete_cls in _load_pydantic_ai_concrete_toolset_classes(toolset_cls):
                    _apply_toolset_call_tool_patch(concrete_cls, self.callback_handler)

        if not tool_hooked:
            set_process_agent_id(None)
            return False

        agent_cls = _load_pydantic_ai_agent_class()
        if agent_cls is not None:
            _apply_agent_run_patch(agent_cls, self.process_agent_id)
        return True

    def revert(self) -> None:
        """Revert Pydantic AI tool and agent patches when available."""
        agent_cls = _load_pydantic_ai_agent_class()
        if agent_cls is not None:
            _revert_agent_run_patch(agent_cls)
        tool_cls = _load_pydantic_ai_tool_class()
        if tool_cls is not None:
            _revert_tool_run_patch(tool_cls)
        toolset_cls = _load_pydantic_ai_toolset_class()
        if toolset_cls is not None:
            for concrete_cls in _load_pydantic_ai_concrete_toolset_classes(toolset_cls):
                _revert_toolset_call_tool_patch(concrete_cls)
            _revert_toolset_call_tool_patch(toolset_cls)
        set_process_agent_id(None)
        return None


class AssemblyModelWrapper:
    """Optional model wrapper for LLM input scan-forward interception."""

    def __init__(self, model: Any, callback_handler: Any) -> None:
        self._model = model
        self._callback_handler = callback_handler

    async def request(self, *args: Any, **kwargs: Any) -> Any:
        scan_method = getattr(self._callback_handler, "on_llm_start_scan", None)
        if callable(scan_method):
            scan_result = scan_method(
                serialized={"name": self._model.__class__.__name__},
                prompts=[str(args[0])] if args else [],
                run_id=kwargs.get("run_id"),
            )
            if inspect.isawaitable(scan_result):
                await scan_result

        result = self._model.request(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._model, name)


def _load_pydantic_ai_tool_class() -> type[Any] | None:
    try:
        module = importlib.import_module("pydantic_ai.tools")
    except ImportError:
        return None

    tool_cls = getattr(module, "Tool", None)
    if isinstance(tool_cls, type):
        return tool_cls
    return None


def _load_pydantic_ai_toolset_class() -> type[Any] | None:
    """Load ``AbstractToolset`` — the >=0.3.0 tool-execution hook point.

    In Pydantic AI >=0.3.0 tool execution routes through
    ``AbstractToolset.call_tool`` rather than ``Tool._run``.
    """
    try:
        module = importlib.import_module("pydantic_ai.toolsets")
    except ImportError:
        return None

    toolset_cls = getattr(module, "AbstractToolset", None)
    if isinstance(toolset_cls, type):
        return toolset_cls
    return None


def _import_module_or_none(module_name: str) -> Any:
    """Import ``module_name``, returning ``None`` when it is not installed."""
    try:
        return importlib.import_module(module_name)
    except ImportError:
        return None


def _import_attr(module_name: str, attr_name: str) -> Any:
    """Import ``module_name`` and return its ``attr_name``, or ``None`` when unavailable."""
    module = _import_module_or_none(module_name)
    if module is None:
        return None
    return getattr(module, attr_name, None)


def _is_own_call_tool_toolset(candidate: Any, base_toolset_cls: type[Any]) -> bool:
    """Return True when ``candidate`` is a concrete subclass overriding its own ``call_tool``."""
    if not isinstance(candidate, type):
        return False
    if candidate is base_toolset_cls:
        return False
    if not issubclass(candidate, base_toolset_cls):
        return False
    return "call_tool" in vars(candidate)


def _load_pydantic_ai_concrete_toolset_classes(base_toolset_cls: type[Any]) -> list[type[Any]]:
    """Return concrete ``AbstractToolset`` subclasses that OVERRIDE ``call_tool``.

    Function tools (``@agent.tool_plain`` / ``@agent.tool``) execute through
    ``pydantic_ai.toolsets.function.FunctionToolset.call_tool``, which overrides
    the abstract base WITHOUT calling ``super().call_tool(...)``. A patch on
    ``AbstractToolset.call_tool`` is therefore shadowed and never runs for them.

    Load ``FunctionToolset`` explicitly, then generically discover any other
    concrete toolset in ``pydantic_ai.toolsets`` that defines its own
    ``call_tool`` (in ``vars(cls)``) so other own-``call_tool`` toolsets are
    covered. Stays fail-soft when Pydantic AI is absent.
    """
    discovered: list[type[Any]] = []
    seen: set[int] = set()

    def _consider(candidate: Any) -> None:
        if not _is_own_call_tool_toolset(candidate, base_toolset_cls):
            return
        if id(candidate) in seen:
            return
        seen.add(id(candidate))
        discovered.append(candidate)

    function_toolset = _import_attr("pydantic_ai.toolsets.function", "FunctionToolset")
    if function_toolset is not None:
        _consider(function_toolset)

    toolsets_module = _import_module_or_none("pydantic_ai.toolsets")
    if toolsets_module is not None:
        for attr_value in vars(toolsets_module).values():
            _consider(attr_value)

    return discovered


def _load_pydantic_ai_agent_class() -> type[Any] | None:
    try:
        module = importlib.import_module("pydantic_ai")
    except ImportError:
        return None

    agent_cls = getattr(module, "Agent", None)
    if isinstance(agent_cls, type):
        return agent_cls
    return None


def _current_spawn_depth() -> int:
    current = _SPAWN_CTX.get()
    return (current.depth + 1) if current is not None else 1


def _apply_agent_run_patch(agent_cls: type[Any], process_agent_id: str | None) -> None:
    if getattr(agent_cls, _AGENT_PATCHED_FLAG, False):
        return None

    original_run = agent_cls.run
    original_run_sync = agent_cls.run_sync

    @wraps(original_run)
    async def patched_run(self: Any, *args: Any, **kwargs: Any) -> Any:
        spawn_ctx = SpawnContext(
            parent_agent_id=process_agent_id or "",
            depth=_current_spawn_depth(),
            spawned_by_tool="pydantic_ai_agent",
        )
        with spawn_context_scope(spawn_ctx):
            result = original_run(self, *args, **kwargs)
            if inspect.isawaitable(result):
                return await result
            return result

    @wraps(original_run_sync)
    def patched_run_sync(self: Any, *args: Any, **kwargs: Any) -> Any:
        spawn_ctx = SpawnContext(
            parent_agent_id=process_agent_id or "",
            depth=_current_spawn_depth(),
            spawned_by_tool="pydantic_ai_agent",
        )
        with spawn_context_scope(spawn_ctx):
            return original_run_sync(self, *args, **kwargs)

    setattr(agent_cls, _ORIGINAL_AGENT_RUN, original_run)
    setattr(agent_cls, _ORIGINAL_AGENT_RUN_SYNC, original_run_sync)
    agent_cls.run = patched_run
    agent_cls.run_sync = patched_run_sync
    setattr(agent_cls, _AGENT_PATCHED_FLAG, True)
    return None


def _revert_agent_run_patch(agent_cls: type[Any]) -> None:
    if not getattr(agent_cls, _AGENT_PATCHED_FLAG, False):
        return None

    for orig_attr, method_name in (
        (_ORIGINAL_AGENT_RUN, "run"),
        (_ORIGINAL_AGENT_RUN_SYNC, "run_sync"),
    ):
        original = getattr(agent_cls, orig_attr, None)
        if callable(original):
            setattr(agent_cls, method_name, original)
        if hasattr(agent_cls, orig_attr):
            delattr(agent_cls, orig_attr)

    if hasattr(agent_cls, _AGENT_PATCHED_FLAG):
        delattr(agent_cls, _AGENT_PATCHED_FLAG)
    return None


def _apply_tool_run_patch(tool_cls: type[Any], callback_handler: Any) -> bool:
    """Patch ``Tool._run`` (the <0.3.0 hook); no-op if it is unavailable."""
    if getattr(tool_cls, _TOOLS_PATCHED_FLAG, False):
        return True

    original_run = getattr(tool_cls, "_run", None)
    if not callable(original_run):
        return False

    @wraps(original_run)
    async def patched_run(self: Any, ctx: Any, args: Any, **kwargs: Any) -> Any:
        tool_name = str(getattr(self, "name", self.__class__.__name__))
        tool_args = _serialize_tool_args(args)
        agent_id = _resolve_agent_id(ctx)
        run_id = _resolve_run_id(ctx)

        decision = await _invoke_async_tool_check(
            callback_handler,
            tool_name=tool_name,
            tool_args=tool_args,
            agent_id=agent_id,
            run_id=run_id,
        )
        status, reason = _normalize_decision(decision)
        is_pending_flow = False
        if status == "pending":
            is_pending_flow = True
            timeout_seconds = _get_pending_tool_approval_timeout_seconds(callback_handler)
            final_decision = await _wait_for_async_tool_approval(
                callback_handler,
                tool_name=tool_name,
                timeout_seconds=timeout_seconds,
                tool_args=tool_args,
                agent_id=agent_id,
                run_id=run_id,
            )
            status, reason = _normalize_decision(final_decision)

        if status == "deny":
            if is_pending_flow:
                raise _build_pending_rejected_error(tool_name, reason)
            raise _build_denied_error(tool_name, reason)

        spawn_ctx = SpawnContext(
            parent_agent_id=agent_id or "",
            depth=_current_spawn_depth(),
            spawned_by_tool=tool_name,
            delegation_reason=f"tool:{tool_name}",
        )
        with spawn_context_scope(spawn_ctx):
            result = original_run(self, ctx, args, **kwargs)
            if inspect.isawaitable(result):
                result = await result

        await _record_async_tool_result(
            callback_handler,
            tool_name=tool_name,
            result=result,
            agent_id=agent_id,
            run_id=run_id,
        )
        return result

    setattr(tool_cls, _ORIGINAL_TOOL_RUN, original_run)
    tool_cls._run = patched_run
    setattr(tool_cls, _TOOLS_PATCHED_FLAG, True)
    return True


def _revert_tool_run_patch(tool_cls: type[Any]) -> None:
    if not getattr(tool_cls, _TOOLS_PATCHED_FLAG, False):
        return None

    original_run = getattr(tool_cls, _ORIGINAL_TOOL_RUN, None)
    if callable(original_run):
        tool_cls._run = original_run

    if hasattr(tool_cls, _ORIGINAL_TOOL_RUN):
        delattr(tool_cls, _ORIGINAL_TOOL_RUN)
    if hasattr(tool_cls, _TOOLS_PATCHED_FLAG):
        delattr(tool_cls, _TOOLS_PATCHED_FLAG)
    return None


def _apply_toolset_call_tool_patch(toolset_cls: type[Any], callback_handler: Any) -> bool:
    """Patch a toolset class's ``call_tool`` (the >=0.3.0 hook); no-op if absent.

    Applies to ``AbstractToolset`` and to each concrete subclass that overrides
    ``call_tool``. The patched-flag is checked on the class's OWN dict, not
    inherited state — a concrete subclass whose base is already patched must
    still be patched directly, otherwise its override shadows governance.
    """
    if vars(toolset_cls).get(_TOOLS_PATCHED_FLAG, False):
        return True

    original_call_tool = getattr(toolset_cls, "call_tool", None)
    if not callable(original_call_tool):
        return False

    @wraps(original_call_tool)
    async def patched_call_tool(self: Any, name: Any, tool_args: Any, ctx: Any, tool: Any, **kwargs: Any) -> Any:
        tool_name = str(name)
        serialized_args = _serialize_tool_args(tool_args)
        agent_id = _resolve_agent_id(ctx)
        run_id = _resolve_run_id(ctx)

        decision = await _invoke_async_tool_check(
            callback_handler,
            tool_name=tool_name,
            tool_args=serialized_args,
            agent_id=agent_id,
            run_id=run_id,
        )
        status, reason = _normalize_decision(decision)
        is_pending_flow = False
        if status == "pending":
            is_pending_flow = True
            timeout_seconds = _get_pending_tool_approval_timeout_seconds(callback_handler)
            final_decision = await _wait_for_async_tool_approval(
                callback_handler,
                tool_name=tool_name,
                timeout_seconds=timeout_seconds,
                tool_args=serialized_args,
                agent_id=agent_id,
                run_id=run_id,
            )
            status, reason = _normalize_decision(final_decision)

        if status == "deny":
            if is_pending_flow:
                raise _build_pending_rejected_error(tool_name, reason)
            raise _build_denied_error(tool_name, reason)

        spawn_ctx = SpawnContext(
            parent_agent_id=agent_id or "",
            depth=_current_spawn_depth(),
            spawned_by_tool=tool_name,
            delegation_reason=f"tool:{tool_name}",
        )
        with spawn_context_scope(spawn_ctx):
            result = original_call_tool(self, name, tool_args, ctx, tool, **kwargs)
            if inspect.isawaitable(result):
                result = await result

        await _record_async_tool_result(
            callback_handler,
            tool_name=tool_name,
            result=result,
            agent_id=agent_id,
            run_id=run_id,
        )
        return result

    setattr(toolset_cls, _ORIGINAL_TOOLSET_CALL_TOOL, original_call_tool)
    toolset_cls.call_tool = patched_call_tool
    setattr(toolset_cls, _TOOLS_PATCHED_FLAG, True)
    return True


def _revert_toolset_call_tool_patch(toolset_cls: type[Any]) -> None:
    # Check the class's OWN dict so reverting the base never clears a concrete
    # subclass's flag (and vice versa); each class restores its own call_tool.
    if not vars(toolset_cls).get(_TOOLS_PATCHED_FLAG, False):
        return None

    original_call_tool = vars(toolset_cls).get(_ORIGINAL_TOOLSET_CALL_TOOL, None)
    if callable(original_call_tool):
        toolset_cls.call_tool = original_call_tool

    if _ORIGINAL_TOOLSET_CALL_TOOL in vars(toolset_cls):
        delattr(toolset_cls, _ORIGINAL_TOOLSET_CALL_TOOL)
    if _TOOLS_PATCHED_FLAG in vars(toolset_cls):
        delattr(toolset_cls, _TOOLS_PATCHED_FLAG)
    return None


def set_process_agent_id(agent_id: str | None) -> None:
    global _PROCESS_AGENT_ID
    _PROCESS_AGENT_ID = agent_id


def _get_process_agent_id() -> str | None:
    if isinstance(_PROCESS_AGENT_ID, str) and _PROCESS_AGENT_ID:
        return _PROCESS_AGENT_ID
    return None


def _resolve_agent_id(ctx: Any) -> str | None:
    deps = getattr(ctx, "deps", None)
    candidate = getattr(deps, "assembly_agent_id", None)
    if isinstance(candidate, str) and candidate:
        return candidate
    return _get_process_agent_id()


def _resolve_run_id(ctx: Any) -> str | None:
    run_id = getattr(ctx, "run_id", None)
    if run_id is None:
        return None
    return str(run_id)


def _serialize_tool_args(args: Any) -> dict[str, Any]:
    if hasattr(args, "model_dump"):
        model_dump = args.model_dump
        if callable(model_dump):
            dumped = model_dump()
            if isinstance(dumped, dict):
                return dict(dumped)

    if isinstance(args, Mapping):
        return dict(args)

    return {"value": str(args)}


def _normalize_decision(
    decision: object,
) -> tuple[Literal["allow", "deny", "pending"], str | None]:
    return _normalize_governance_decision(decision)


async def _invoke_async_tool_check(
    callback_handler: Any,
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    agent_id: str | None,
    run_id: str | None,
) -> object:
    method = getattr(callback_handler, "check_tool_start", None)
    if not callable(method):
        return {"status": "allow"}

    result = method(
        serialized={"name": tool_name},
        input_str=str(tool_args),
        tool_name=tool_name,
        args=tool_args,
        agent_id=agent_id,
        run_id=run_id,
    )
    if inspect.isawaitable(result):
        return await result
    return result


async def _wait_for_async_tool_approval(
    callback_handler: Any,
    *,
    tool_name: str,
    timeout_seconds: int,
    tool_args: dict[str, Any],
    agent_id: str | None,
    run_id: str | None,
) -> object:
    method = getattr(callback_handler, "wait_for_tool_approval", None)
    if not callable(method):
        return {"status": "deny", "reason": "Approval handler is unavailable."}

    result = method(
        serialized={"name": tool_name},
        input_str=str(tool_args),
        tool_name=tool_name,
        timeout_seconds=timeout_seconds,
        args=tool_args,
        agent_id=agent_id,
        run_id=run_id,
    )
    if inspect.isawaitable(result):
        return await result
    return result


def _get_pending_tool_approval_timeout_seconds(callback_handler: Any) -> int:
    return _resolve_pending_timeout_seconds(callback_handler)


def _truncate_result_for_audit(result: object) -> str:
    return str(result)[:_MAX_AUDIT_RESULT_CHARS]


async def _record_async_tool_result(
    callback_handler: Any,
    *,
    tool_name: str,
    result: object,
    agent_id: str | None,
    run_id: str | None,
) -> None:
    record_method = getattr(callback_handler, "record_result", None)
    if callable(record_method):
        recorded = record_method(
            tool_name=tool_name,
            result=_truncate_result_for_audit(result),
            agent_id=agent_id,
            run_id=run_id,
        )
        if inspect.isawaitable(recorded):
            await recorded
        return None

    tool_end_method = getattr(callback_handler, "on_tool_end", None)
    if callable(tool_end_method):
        recorded = tool_end_method(
            output=_truncate_result_for_audit(result),
            tool_name=tool_name,
            agent_id=agent_id,
            run_id=run_id,
        )
        if inspect.isawaitable(recorded):
            await recorded


def _build_denied_error(tool_name: str, reason: str | None) -> Exception:
    from agent_assembly.exceptions import PolicyViolationError

    reason_text = reason or "No reason provided."
    return PolicyViolationError(f"Tool '{tool_name}' blocked by governance policy: {reason_text}")


def _build_pending_rejected_error(tool_name: str, reason: str | None) -> Exception:
    from agent_assembly.exceptions import PolicyViolationError

    reason_text = reason or "No reason provided."
    return PolicyViolationError(f"Tool '{tool_name}' rejected during approval: {reason_text}")
