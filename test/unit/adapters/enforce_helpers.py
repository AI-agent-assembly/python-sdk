"""Shared stand-ins for the AAASM-4734 fail-closed-under-enforce regression tests.

Every governed adapter must DENY (not fall open) under an enforce posture for two
inputs that previously slipped through: a malformed/unrecognized verdict, and an
interceptor exposing no ``check_tool_start``. The interceptor stand-ins and the
parametrization list are shared here so the four adapters' tests exercise both
scenarios without copy-pasting the same arrange/assert into each file (which
SonarCloud otherwise flags as duplicated lines).
"""

from __future__ import annotations

import pytest


class EnforcingUnknownInterceptor:
    """Enforcing interceptor whose ``check_tool_start`` returns a malformed verdict.

    ``_enforce = True`` marks the fail-closed posture; ``None`` is an unrecognized
    verdict that must be denied rather than silently allowed.
    """

    _enforce = True

    async def check_tool_start(self, **kwargs: object) -> object:
        del kwargs
        return None


class EnforcingHandlerWithoutCheck:
    """Enforcing handler that exposes no ``check_tool_start`` at all.

    The missing-method path must fail closed under enforce instead of the former
    hardcoded allow.
    """

    _enforce = True


# Both fail-closed scenarios as interceptor-factory params. Adapters that cover
# both cases (openai_agents / pydantic_ai / google_adk) parametrize their deny
# test over this list; mcp already had the malformed-verdict test, so it uses the
# missing-check handler directly.
ENFORCE_DENY_CASES = [
    pytest.param(EnforcingUnknownInterceptor, id="unknown_verdict"),
    pytest.param(EnforcingHandlerWithoutCheck, id="missing_check_tool_start"),
]
