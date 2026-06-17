"""Governed pre-execution check backed by the native runtime ``query_policy``.

Wave 3 of AAASM-3021 (AAASM-3049). The framework adapters call
``check_tool_start(...)`` on the governance interceptor before a tool runs and
block when it reports a ``deny``. In production wiring the adapters are handed
the :class:`~agent_assembly.client.gateway.GatewayClient`, which has no
``check_tool_start`` — so that deny branch was dead.

:class:`RuntimeQueryInterceptor` wraps the ``GatewayClient`` and adds a
``check_tool_start`` that asks a connected
``agent_assembly._core.RuntimeClient`` whether the tool call is allowed, via
``query_policy``. The runtime is the authority: it redacts in place, so this
layer only ever *blocks* on an explicit ``deny`` and otherwise proceeds.

Failure posture is governed by ``enforcement_mode`` (AAASM-3106):

* Under ``enforce``, the SDK is a security control and **fails closed**. When the
  native extension is missing the bare client is returned (no native authority
  exists to consult — see :func:`build_governance_interceptor`), but once the
  native extension is present every other failure denies: an unreachable runtime
  socket yields a deny-all interceptor, a raising ``query_policy`` maps to
  ``deny``, and a native ``decision`` that is itself an error sentinel
  (``query_failed`` / ``channel_closed``) maps to ``deny`` rather than allow.
* Under ``observe`` / ``disabled`` (or when no mode is supplied), the SDK is a
  dry-run / hermetic-test layer and **fails open**: an unreachable runtime
  returns the bare client unchanged, a raising or error ``query_policy``
  proceeds, exactly as before.

The runtime remains the authority on *redaction* (it redacts in place); this
layer only ever decides allow / deny / pending.
"""

from __future__ import annotations

import json
import os
from typing import Any

ENV_RUNTIME_SOCKET = "AA_RUNTIME_SOCKET"
ACTION_TYPE_TOOL_CALL = "tool_call"
ENFORCE_MODE = "enforce"

# Native ``query_policy`` decisions that signal the runtime could not produce an
# authoritative verdict (mirrors aa-ffi-python mapping QueryFailed / ChannelClosed
# / Shutdown). Under ``enforce`` these must deny, not allow (AAASM-3106).
_ERROR_DECISIONS = frozenset({"query_failed", "channel_closed", "shutdown", "error"})


def _resolve_runtime_socket_path(agent_id: str) -> str:
    """Resolve the runtime UDS path: ``AA_RUNTIME_SOCKET`` > default convention.

    Mirrors ``aa-ffi-python``'s ``AssemblyConfig::resolve_socket_path``: the
    ``AA_RUNTIME_SOCKET`` environment variable takes precedence, otherwise the
    per-agent default ``/tmp/aa-runtime-<agent_id>.sock`` is used.

    Note: the ``/tmp/aa-runtime-<agent_id>.sock`` literal mirrors the canonical
    path baked into ``aa-sdk-client::AssemblyConfig::resolve_socket_path`` on the
    Rust side. This path is the SDK↔runtime IPC contract: ``aa-runtime`` binds
    the UDS server here and every SDK (Python, Node, Go) connects here. The SDK
    only *connects* to a path the runtime created; it never writes the socket
    itself. Operators who need to relocate the socket (e.g. multi-tenant hosts)
    set ``AA_RUNTIME_SOCKET`` to override. Replacing the literal with
    ``tempfile.gettempdir()`` would break interop on platforms where it does not
    resolve to ``/tmp`` (notably macOS dev hosts).
    """
    env_path = os.environ.get(ENV_RUNTIME_SOCKET)
    if env_path:
        return env_path
    # IPC contract path (see docstring above). The SDK is a *client* of a
    # socket the runtime creates; this code never writes to /tmp itself.
    # SonarCloud python:S5443 is suppressed project-wide for this file via
    # sonar-project.properties; ruff S108 is suppressed inline below.
    return f"/tmp/aa-runtime-{agent_id}.sock"  # noqa: S108


def _extract_tool_name(serialized: Any, kwargs: dict[str, Any]) -> str | None:
    """Best-effort tool-name extraction from a ``check_tool_start`` call.

    Adapters pass ``serialized={"name": tool_name}`` and a ``tool_name`` kwarg.
    Prefer the explicit ``tool_name`` and fall back to ``serialized["name"]``.
    """
    tool_name = kwargs.get("tool_name")
    if isinstance(tool_name, str) and tool_name:
        return tool_name
    if isinstance(serialized, dict):
        name = serialized.get("name")
        if isinstance(name, str) and name:
            return name
    return None


def _extract_tool_args_json(input_str: Any, kwargs: dict[str, Any]) -> str | None:
    """Serialize the tool arguments to JSON for the native ``query_policy``.

    Adapters pass structured ``args`` and/or a stringified ``input_str``. Prefer
    structured ``args`` (JSON-encoded); fall back to ``input_str`` wrapped as a
    JSON string. Returns ``None`` when nothing usable is present.
    """
    args = kwargs.get("args")
    if args is not None:
        try:
            return json.dumps(args, default=str)
        except (TypeError, ValueError):
            return json.dumps(str(args))
    if isinstance(input_str, str) and input_str:
        return json.dumps(input_str)
    return None


class RuntimeQueryInterceptor:
    """Adapter interceptor that enforces the runtime's pre-execution decision.

    Delegates every attribute the adapters look up (event reporting, tool-end
    hooks, approval timeout providers, ...) to the wrapped ``GatewayClient`` and
    only *adds* ``check_tool_start``.

    The failure posture of the added check is governed by ``enforce``: when
    ``True`` (``enforcement_mode == "enforce"``) any path that cannot obtain an
    authoritative allow — a raising ``query_policy`` or an error-sentinel
    ``decision`` — maps to ``deny`` (fail closed). When ``False`` those paths
    proceed (fail open), preserving the observe / disabled behavior.
    """

    def __init__(self, client: Any, runtime_client: Any, agent_id: str, *, enforce: bool = False) -> None:
        self._client = client
        self._runtime_client = runtime_client
        self._agent_id = agent_id
        self._enforce = enforce

    def __getattr__(self, name: str) -> Any:
        # Delegate anything not defined here (e.g. report_event, on_tool_end,
        # approval-timeout providers) to the wrapped GatewayClient so existing
        # adapter behavior is preserved unchanged.
        return getattr(self._client, name)

    def check_tool_start(
        self,
        *,
        serialized: Any = None,
        input_str: Any = None,
        **kwargs: Any,
    ) -> dict[str, str]:
        """Ask the runtime whether this tool call may proceed.

        Maps the runtime decision onto the adapter contract:

        * ``"deny"`` → ``{"status": "deny", "reason": ...}``.
        * ``"pending"`` → ``{"status": "pending", "reason": ...}`` so the
          adapter's existing approval path runs.
        * ``"allow"`` / ``"redact"`` / ``"unspecified"`` → ``{"status": "allow"}``.
          The runtime redacts authoritatively; this layer never redacts.
        * A raising ``query_policy`` or an error-sentinel ``decision``
          (``query_failed`` / ``channel_closed`` / ``shutdown``) → ``deny`` under
          ``enforce`` (fail closed, AAASM-3106), else ``allow`` (fail open).
        """
        tool_name = _extract_tool_name(serialized, kwargs)
        tool_args_json = _extract_tool_args_json(input_str, kwargs)

        try:
            result = self._runtime_client.query_policy(
                self._agent_id,
                ACTION_TYPE_TOOL_CALL,
                tool_name,
                tool_args_json,
            )
        except Exception:
            # Native query raised — the runtime gave no verdict. Under enforce the
            # SDK is a security control and must block (fail closed); otherwise
            # proceed (fail open).
            return self._on_query_failure("runtime query failed")

        decision = str(result.get("decision", "allow")).strip().lower()
        reason = str(result.get("reason", "") or "")

        if decision == "deny":
            return {"status": "deny", "reason": reason}
        if decision == "pending":
            return {"status": "pending", "reason": reason}
        if decision in _ERROR_DECISIONS:
            # Native reported it could not reach an authoritative verdict.
            return self._on_query_failure(reason or f"runtime returned {decision}")
        return {"status": "allow"}

    def _on_query_failure(self, reason: str) -> dict[str, str]:
        """Map an unauthoritative query to deny (enforce) or allow (observe)."""
        if self._enforce:
            return {"status": "deny", "reason": reason}
        return {"status": "allow"}


class _FailClosedInterceptor:
    """Deny-all interceptor used under ``enforce`` when no runtime is reachable.

    The native extension is present (so the SDK is configured as a security
    control) but the runtime socket could not be connected, meaning no
    authoritative verdict can be obtained. Under ``enforce`` this must block
    every tool rather than silently allow it (AAASM-3106). Non-check attributes
    delegate to the wrapped ``GatewayClient`` so event reporting still works.
    """

    def __init__(self, client: Any, reason: str) -> None:
        self._client = client
        self._reason = reason

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def check_tool_start(self, **_kwargs: Any) -> dict[str, str]:
        return {"status": "deny", "reason": self._reason}


def build_governance_interceptor(client: Any, agent_id: str, enforcement_mode: str | None = None) -> Any:
    """Return the interceptor adapters should use for pre-execution checks.

    When the native extension is importable and a runtime socket is reachable,
    wrap ``client`` in a :class:`RuntimeQueryInterceptor` so a runtime ``deny``
    actually blocks the tool. The failure posture depends on ``enforcement_mode``
    (AAASM-3106):

    * The native extension is **missing**: return ``client`` unchanged in every
      mode. There is no native authority to consult, so there is nothing to fail
      closed *to* — the SDK fast path is simply not engaged.
    * The native extension is **present** but the runtime socket is unreachable:
      under ``enforce`` return a deny-all :class:`_FailClosedInterceptor`;
      otherwise return ``client`` unchanged (fail open).
    """
    enforce = enforcement_mode == ENFORCE_MODE
    try:
        from agent_assembly._core import RuntimeClient
    except ImportError:
        # No native fast path at all — the SDK control is not engaged in any mode.
        return client

    socket_path = _resolve_runtime_socket_path(agent_id)
    try:
        runtime_client = RuntimeClient.connect(socket_path)
    except Exception:
        # Native present but runtime unreachable: deny everything under enforce
        # (fail closed); proceed under observe / disabled (fail open).
        if enforce:
            return _FailClosedInterceptor(client, "runtime unreachable")
        return client

    return RuntimeQueryInterceptor(client, runtime_client, agent_id, enforce=enforce)
