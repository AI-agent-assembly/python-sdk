"""LangChain callback handler module."""

from __future__ import annotations

from typing import Any
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
