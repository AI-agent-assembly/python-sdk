"""LangChain callback handler module."""

from __future__ import annotations

from typing import Any, Literal, Mapping
from uuid import UUID

try:  # pragma: no cover - import availability depends on installed extras.
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError:  # pragma: no cover - fallback keeps runtime import-safe.
    class BaseCallbackHandler:  # type: ignore[no-redef]
        """Fallback base type when langchain-core is not installed."""

        pass


class AssemblyCallbackHandler(BaseCallbackHandler):
    """Callback handler that delegates runtime events to governance interception."""

    def __init__(self, interceptor: Any) -> None:
        self._interceptor = interceptor

    def _normalize_decision(
        self,
        decision: object,
    ) -> tuple[Literal["allow", "deny", "pending"], str | None]:
        if isinstance(decision, str):
            normalized = decision.strip().lower()
            if normalized in {"allow", "deny", "pending"}:
                return normalized, None
            return "allow", None

        if isinstance(decision, Mapping):
            raw_status = str(decision.get("status", "allow")).strip().lower()
            status: Literal["allow", "deny", "pending"]
            if raw_status in {"allow", "deny", "pending"}:
                status = raw_status
            else:
                status = "allow"

            reason_value = decision.get("reason")
            reason = str(reason_value) if reason_value is not None else None
            return status, reason

        return "allow", None

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        del serialized, input_str, run_id, kwargs
        return None

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        del output, run_id, kwargs
        return None

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        del serialized, prompts, run_id, kwargs
        return None

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        del response, run_id, kwargs
        return None
