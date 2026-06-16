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

Fail-open is preserved at two levels:

* When the native extension is missing or no runtime socket is reachable,
  :func:`build_governance_interceptor` returns the bare ``GatewayClient``
  unchanged — no ``check_tool_start`` is present and the adapters proceed
  exactly as before.
* When a runtime *is* connected, the native ``query_policy`` already returns
  ``decision="allow"`` on QueryFailed / ChannelClosed / Shutdown, so a
  transient runtime outage proceeds rather than blocks.
"""

from __future__ import annotations

import json
import os
from typing import Any

ENV_RUNTIME_SOCKET = "AA_RUNTIME_SOCKET"
ACTION_TYPE_TOOL_CALL = "tool_call"


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
    # NOSONAR python:S5443 -- IPC contract path; see docstring above. The SDK
    # is a *client* of a socket the runtime creates; this code never writes to
    # /tmp itself.
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
    only *adds* ``check_tool_start``. The added check is fail-open: any path that
    cannot produce an explicit ``deny`` proceeds.
    """

    def __init__(self, client: Any, runtime_client: Any, agent_id: str) -> None:
        self._client = client
        self._runtime_client = runtime_client
        self._agent_id = agent_id

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

        * ``"deny"`` → ``{"status": "deny", "reason": ...}`` (the only block).
        * ``"pending"`` → ``{"status": "pending", "reason": ...}`` so the
          adapter's existing approval path runs.
        * anything else (``"allow"`` / ``"redact"`` / ``"unspecified"`` / an
          unreachable runtime) → ``{"status": "allow"}``. The runtime redacts
          authoritatively; this layer never redacts.
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
            # Native query raised unexpectedly — fail OPEN, never block.
            return {"status": "allow"}

        decision = str(result.get("decision", "allow")).strip().lower()
        reason = str(result.get("reason", "") or "")

        if decision == "deny":
            return {"status": "deny", "reason": reason}
        if decision == "pending":
            return {"status": "pending", "reason": reason}
        return {"status": "allow"}


def build_governance_interceptor(client: Any, agent_id: str) -> Any:
    """Return the interceptor adapters should use for pre-execution checks.

    When the native extension is importable and a runtime socket is reachable,
    wrap ``client`` in a :class:`RuntimeQueryInterceptor` so a runtime ``deny``
    actually blocks the tool. Otherwise return ``client`` unchanged so the
    existing fail-open / no-core path is preserved exactly.
    """
    try:
        from agent_assembly._core import RuntimeClient
    except ImportError:
        return client

    socket_path = _resolve_runtime_socket_path(agent_id)
    try:
        runtime_client = RuntimeClient.connect(socket_path)
    except Exception:
        # No reachable runtime / connect failed — fail OPEN: bare client has no
        # check_tool_start, so adapters proceed exactly as before.
        return client

    return RuntimeQueryInterceptor(client, runtime_client, agent_id)
