"""Result type for `GatewayClient.dispatch_tool` (AAASM-1920 / Secret Injection)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DispatchToolResult:
    """
    Outcome of a successful ``dispatch_tool`` call.

    The gateway resolves every ``${NAME}`` placeholder in the args via the
    registered ``SecretsStore``, emits a placeholder-form audit entry, and
    returns this object back to the SDK caller.

    Attributes:
        resolved_args: Post-substitution args. Carries the *resolved*
            credential values; do not log this or pass it to the LLM.
        names_substituted: The placeholder names that were resolved during
            this call. Names only — never the resolved values. Echoes the
            audit-log shape so callers can correlate dispatches with audit
            entries by ``names_substituted`` set.
    """

    resolved_args: dict[str, Any]
    names_substituted: list[str] = field(default_factory=list)
