"""Result type for `GatewayClient.dispatch_tool` (AAASM-1920 / Secret Injection)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ``repr=False``: ``resolved_args`` holds resolved secret values, so the
# dataclass-generated ``__repr__`` (which renders every field verbatim) would
# leak them into logs/tracebacks. We supply a redacting ``__repr__`` instead.
@dataclass(frozen=True, repr=False)
class DispatchToolResult:
    """
    Outcome of a successful ``dispatch_tool`` call.

    The gateway resolves every ``${NAME}`` placeholder in the args via the
    registered ``SecretsStore``, emits a placeholder-form audit entry, and
    returns this object back to the SDK caller.

    Attributes:
        resolved_args: Post-substitution args. Carries the *resolved*
            credential values; do not log this or pass it to the LLM. The
            ``repr``/``str`` of this object deliberately masks these values
            (key names and count only) so they cannot leak via logging.
        names_substituted: The placeholder names that were resolved during
            this call. Names only — never the resolved values. Echoes the
            audit-log shape so callers can correlate dispatches with audit
            entries by ``names_substituted`` set.
    """

    resolved_args: dict[str, Any]
    names_substituted: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        """Render without exposing resolved secret values.

        Shows the argument *keys* and their count in place of the resolved
        values, so the result can be safely logged or appear in tracebacks.
        ``names_substituted`` is names-only by contract and is shown verbatim.
        """
        keys = sorted(self.resolved_args)
        return (
            "DispatchToolResult("
            f"resolved_args=<redacted: {len(keys)} value(s) for keys {keys}>, "
            f"names_substituted={self.names_substituted!r})"
        )

    __str__ = __repr__
