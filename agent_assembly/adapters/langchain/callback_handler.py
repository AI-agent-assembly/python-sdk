"""LangChain callback handler module."""

from __future__ import annotations

import importlib
import inspect
from typing import Any, Literal, Mapping, cast
from uuid import UUID

from agent_assembly.exceptions import ToolExecutionBlockedError


class _FallbackBaseCallbackHandler:
    """Fallback base type when langchain-core is not installed."""


_CallbackHandlerBase: type[object] = _FallbackBaseCallbackHandler
try:  # pragma: no cover - import availability depends on installed extras.
    callbacks_module = importlib.import_module("langchain_core.callbacks")
    maybe_base = getattr(callbacks_module, "BaseCallbackHandler", _FallbackBaseCallbackHandler)
    if isinstance(maybe_base, type):
        _CallbackHandlerBase = cast(type[object], maybe_base)
except ImportError:  # pragma: no cover - fallback keeps runtime import-safe.
    pass


class AssemblyCallbackHandler(_CallbackHandlerBase):  # type: ignore[valid-type,misc]
    """Callback handler that delegates runtime events to governance interception."""

    _UNKNOWN_DECISION_REASON = "Unrecognized governance decision; denied under enforce."

    def __init__(self, interceptor: Any) -> None:
        self._interceptor = interceptor

    @property
    def _enforce(self) -> bool:
        """Whether the wired interceptor is in fail-closed ``enforce`` posture.

        The governance interceptor (``RuntimeQueryInterceptor`` /
        ``_FailClosedInterceptor``) carries ``_enforce`` set from
        ``enforcement_mode == "enforce"`` (AAASM-3106). A bare ``GatewayClient``
        — used when no native runtime authority is engaged — lacks it and
        defaults to fail-open. AAASM-3107 reuses this flag so an unknown / ``None``
        / malformed verdict denies under enforce instead of silently allowing.

        Compared strictly against ``True`` so a stub interceptor whose
        ``__getattr__`` synthesizes truthy values for missing attributes is not
        mistaken for the enforce posture; the real flag is always a ``bool``.
        """
        return getattr(self._interceptor, "_enforce", False) is True

    def _unknown_decision(self) -> tuple[Literal["allow", "deny", "pending"], str | None]:
        """Map an unrecognized / malformed verdict, failing closed under enforce.

        Under ``enforce`` an unknown, ``None``, or malformed verdict must not be
        silently allowed (AAASM-3107), so it denies. Under ``observe`` /
        ``disabled`` it proceeds (fail open).
        """
        if self._enforce:
            return "deny", self._UNKNOWN_DECISION_REASON
        return "allow", None

    def _normalize_decision(
        self,
        decision: object,
    ) -> tuple[Literal["allow", "deny", "pending"], str | None]:
        if isinstance(decision, str):
            normalized = decision.strip().lower()
            if normalized == "allow":
                return "allow", None
            if normalized == "deny":
                return "deny", None
            if normalized == "pending":
                return "pending", None
            return self._unknown_decision()

        if isinstance(decision, Mapping):
            raw_status = str(decision.get("status", "")).strip().lower()
            reason_value = decision.get("reason")
            reason = str(reason_value) if reason_value is not None else None
            if raw_status == "allow":
                return "allow", reason
            if raw_status == "deny":
                return "deny", reason
            if raw_status == "pending":
                return "pending", reason
            unknown_status, unknown_reason = self._unknown_decision()
            return unknown_status, reason if reason is not None else unknown_reason

        return self._unknown_decision()

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        method = getattr(self._interceptor, "check_tool_start", None)
        if not callable(method):
            return None

        decision = method(
            serialized=serialized,
            input_str=input_str,
            run_id=run_id,
            **kwargs,
        )
        status, reason = self._normalize_decision(decision)
        if status == "deny":
            raise ToolExecutionBlockedError(reason or "Tool execution blocked by governance.")
        if status == "pending":
            approval = self._resolve_pending_approval(
                serialized=serialized,
                input_str=input_str,
                run_id=run_id,
                **kwargs,
            )
            approval_status, approval_reason = self._normalize_decision(approval)
            if approval_status != "allow":
                raise ToolExecutionBlockedError(
                    approval_reason or reason or "Tool execution was not approved by governance."
                )

        return None

    def _resolve_pending_approval(
        self,
        *,
        serialized: dict[str, Any],
        input_str: str,
        run_id: UUID,
        **kwargs: Any,
    ) -> object:
        wait_method = getattr(self._interceptor, "wait_for_tool_approval", None)
        if not callable(wait_method):
            return "deny"

        return wait_method(
            serialized=serialized,
            input_str=input_str,
            run_id=run_id,
            **kwargs,
        )

    async def aon_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        method = getattr(self._interceptor, "check_tool_start", None)
        if not callable(method):
            return None

        decision = method(
            serialized=serialized,
            input_str=input_str,
            run_id=run_id,
            **kwargs,
        )
        if inspect.isawaitable(decision):
            decision = await decision

        status, reason = self._normalize_decision(decision)
        if status == "deny":
            raise ToolExecutionBlockedError(reason or "Tool execution blocked by governance.")
        if status == "pending":
            approval = self._resolve_pending_approval(
                serialized=serialized,
                input_str=input_str,
                run_id=run_id,
                **kwargs,
            )
            if inspect.isawaitable(approval):
                approval = await approval
            approval_status, approval_reason = self._normalize_decision(approval)
            if approval_status != "allow":
                raise ToolExecutionBlockedError(
                    approval_reason or reason or "Tool execution was not approved by governance."
                )

        return None

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        method = getattr(self._interceptor, "on_tool_end", None)
        if not callable(method):
            return None

        method(
            output=output,
            run_id=run_id,
            **kwargs,
        )
        return None

    async def aon_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        method = getattr(self._interceptor, "on_tool_end", None)
        if not callable(method):
            return None

        result = method(
            output=output,
            run_id=run_id,
            **kwargs,
        )
        if inspect.isawaitable(result):
            await result
        return None

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        method = getattr(self._interceptor, "on_llm_start_scan", None)
        if not callable(method):
            return None

        method(
            serialized=serialized,
            prompts=prompts,
            run_id=run_id,
            **kwargs,
        )
        return None

    async def aon_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        method = getattr(self._interceptor, "on_llm_start_scan", None)
        if not callable(method):
            return None

        result = method(
            serialized=serialized,
            prompts=prompts,
            run_id=run_id,
            **kwargs,
        )
        if inspect.isawaitable(result):
            await result
        return None

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        method = getattr(self._interceptor, "on_llm_end", None)
        if not callable(method):
            return None

        method(
            response=response,
            run_id=run_id,
            **kwargs,
        )
        return None

    async def aon_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        method = getattr(self._interceptor, "on_llm_end", None)
        if not callable(method):
            return None

        result = method(
            response=response,
            run_id=run_id,
            **kwargs,
        )
        if inspect.isawaitable(result):
            await result
        return None

    def on_graph_node_start(
        self,
        node_name: str,
        state: Any,
        *,
        agent_id: str | None = None,
        state_keys: list[str] | None = None,
        config: Any = None,
    ) -> None:
        method = getattr(self._interceptor, "on_graph_node_start", None)
        if not callable(method):
            return None
        method(
            node_name=node_name,
            agent_id=agent_id,
            state=state,
            state_keys=state_keys,
            config=config,
        )
        return None

    def on_graph_node_end(
        self,
        node_name: str,
        state: Any,
        result: Any,
        *,
        agent_id: str | None = None,
        state_delta: dict[str, Any] | None = None,
        config: Any = None,
    ) -> None:
        method = getattr(self._interceptor, "on_graph_node_end", None)
        if not callable(method):
            return None
        method(
            node_name=node_name,
            agent_id=agent_id,
            state=state,
            result=result,
            state_delta=state_delta,
            config=config,
        )
        return None
