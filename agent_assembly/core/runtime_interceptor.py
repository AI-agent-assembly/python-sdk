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

* Under an **enforce** posture — explicit ``enforce`` *or* the ``None`` default,
  which is advertised as the gateway's live ``enforce`` (AAASM-4130) — the SDK is
  a security control and **fails closed**. When the native extension is missing the
  bare client is returned (no native authority exists to consult — see
  :func:`build_governance_interceptor`) but a loud one-time warning is emitted so the
  skipped in-process deny is not silent; once the native extension is present every
  other failure denies: an unreachable runtime socket yields a deny-all interceptor,
  a raising ``query_policy`` maps to ``deny``, and a native ``decision`` that is
  itself an error sentinel (``query_failed`` / ``channel_closed``) maps to ``deny``
  rather than allow.
* Under the explicit dry-run postures **observe** / **disabled**, the SDK is a
  dry-run / hermetic-test layer and **fails open**: an unreachable runtime
  returns the bare client unchanged, a raising or error ``query_policy``
  proceeds, exactly as before.

The runtime remains the authority on *redaction* (it redacts in place); this
layer only ever decides allow / deny / pending.
"""

from __future__ import annotations

import json
import os
import stat
import warnings
from importlib import metadata
from typing import Any

from agent_assembly.exceptions import OpTerminatedError

ENV_RUNTIME_SOCKET = "AA_RUNTIME_SOCKET"
ACTION_TYPE_TOOL_CALL = "tool_call"
ENFORCE_MODE = "enforce"

# Native ``query_policy`` decisions that signal the runtime could not produce an
# authoritative verdict (mirrors aa-ffi-python mapping QueryFailed / ChannelClosed
# / Shutdown). Under ``enforce`` these must deny, not allow (AAASM-3106).
_ERROR_DECISIONS = frozenset({"query_failed", "channel_closed", "shutdown", "error"})

# Native decisions that authoritatively permit the tool to proceed. ``deny`` and
# ``pending`` are handled explicitly; only these are treated as an allow. Anything
# else — the proto3 zero value ``unspecified`` ("no decision rendered"), an unknown
# string, an empty value, or a missing ``decision`` key — is not an authoritative
# allow and must fail closed under ``enforce`` (AAASM-4014, AAASM-4166), matching the
# Node SDK; the runtime remains the authority on redaction, so ``redact`` proceeds.
_ALLOW_DECISIONS = frozenset({"allow", "redact"})


def _local_posture_is_enforce(enforcement_mode: str | None) -> bool:
    """Whether the SDK's *local* failure posture must fail closed (AAASM-4130).

    ``enforcement_mode is None`` is the advertised default: it registers the agent
    under the gateway's server-side default, which is live ``enforce``. So for the
    SDK's own error posture ``None`` must behave exactly like ``enforce`` — an
    unreachable runtime or an unauthoritative query denies rather than silently
    proceeding. Only the explicit dry-run postures (``observe`` / ``disabled``) fail
    open locally.
    """
    return enforcement_mode is None or enforcement_mode == ENFORCE_MODE


def _warn_sdk_enforcement_unavailable() -> None:
    """Warn (loudly, once) that no *local* pre-execution deny can run (AAASM-4130).

    Under an enforce posture (the ``None`` default or explicit ``enforce``) a policy
    ``deny`` is advertised to block the tool before it runs, but that in-process fast
    path needs the native ``agent_assembly._core`` extension. On a pure-Python install
    it is absent, so no local deny is possible. Rather than silently fail open (Python
    diverging from go's fail-closed and node's ``ConfigurationError``), emit a warning
    so the gap is visible; the gateway / proxy / eBPF layers remain authoritative, so
    the SDK stays advisory and does not hard-fail on a missing runtime.
    """
    warnings.warn(
        "Agent Assembly enforcement is active but the native runtime extension "
        "(agent_assembly._core) is not installed, so the SDK cannot apply a local "
        "pre-execution deny; tool calls proceed in-process and rely on the gateway / "
        "proxy / eBPF layers for enforcement. Install the native extension to enable "
        "the in-process deny fast path.",
        stacklevel=2,
    )


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

    Security (AAASM-3920): ``/tmp`` is world-traversable, so the default path is
    predictable and any local user can pre-create it to impersonate the runtime.
    The path itself is kept as the cross-platform IPC default to preserve interop
    with the Rust runtime's bind path, but two mitigations apply:

    * For hardened multi-user hosts, set ``AA_RUNTIME_SOCKET`` to a socket inside
      a per-user ``0700`` runtime directory (e.g. under ``$XDG_RUNTIME_DIR``) so
      the path is not world-traversable. The override is honoured unchanged.
    * Before connecting to the *default* path, :func:`connect_runtime_client`
      verifies the socket is owned by the current user (see
      :func:`_runtime_socket_is_trusted`) and refuses a foreign-owned squat,
      failing closed under ``enforce``.

    Robust peer-credential validation (``SO_PEERCRED`` of the connected peer) is
    the Rust ``aa-sdk-client``'s responsibility; this module only does a
    best-effort pre-connect ownership check.
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


def _extract_op_id(kwargs: dict[str, Any]) -> str | None:
    """Resolve the op id ("{trace_id}:{span_id}") from a check_tool_start call.

    Prefers an explicit ``op_id`` kwarg; otherwise composes it from
    ``trace_id`` / ``span_id`` when an adapter supplies them. Returns ``None``
    when no trace identity is present (the call is not part of a tracked op, so
    there is nothing for the kill switch to address).
    """
    op_id = kwargs.get("op_id")
    if isinstance(op_id, str) and op_id:
        return op_id
    trace_id = kwargs.get("trace_id")
    if isinstance(trace_id, str) and trace_id:
        span_id = kwargs.get("span_id")
        span = span_id if isinstance(span_id, str) else ""
        return f"{trace_id}:{span}"
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
    ``True`` (an enforce posture — explicit ``enforce`` or the ``None`` default,
    resolved in :func:`build_governance_interceptor`) any path that cannot obtain
    an authoritative allow — a raising ``query_policy`` or an error-sentinel
    ``decision`` — maps to ``deny`` (fail closed). When ``False`` those paths
    proceed (fail open), preserving the observe / disabled behavior.
    """

    def __init__(
        self,
        client: Any,
        runtime_client: Any,
        agent_id: str,
        *,
        enforce: bool = False,
        op_control: Any | None = None,
    ) -> None:
        self._client = client
        self._runtime_client = runtime_client
        self._agent_id = agent_id
        self._enforce = enforce
        # Optional live op-control consumer (AAASM-3491). When wired, the
        # gateway's kill switch is honored *in this tool path*: a terminate
        # fast-fails the call and a pause blocks it cooperatively before the
        # runtime is even queried. Without it, op control only reaches the agent
        # via the native runtime's own OpControlStream consumer.
        self._op_control = op_control

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
        * ``"allow"`` / ``"redact"`` → ``{"status": "allow"}``. The runtime
          redacts authoritatively; this layer never redacts.
        * A raising ``query_policy``, the proto3 zero value ``"unspecified"``
          ("no decision rendered"), an error-sentinel ``decision``
          (``query_failed`` / ``channel_closed`` / ``shutdown``), or any
          unrecognized decision → ``deny`` under ``enforce`` (fail closed,
          AAASM-3106 / AAASM-4166, matching Node), else ``allow`` (fail open).

        Before any of the above, the live op-control kill switch (AAASM-3491) is
        consulted when an ``op_id`` is supplied and a subscriber is wired: a
        terminated op is denied immediately and a paused op blocks here until
        the gateway resumes it, so an operator terminate/pause reaches this tool
        path directly rather than relying solely on the native runtime.
        """
        op_block = self._check_op_control(_extract_op_id(kwargs))
        if op_block is not None:
            return op_block

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

        # A non-dict result (e.g. ``None`` from a malformed/partial runtime
        # response) is not an authoritative verdict; route it through the
        # fail-closed path rather than raising ``AttributeError`` on ``.get``
        # (AAASM-4167).
        if not isinstance(result, dict):
            return self._on_query_failure("runtime returned non-dict result")

        # No ``"allow"`` default: a missing / empty ``decision`` is not an
        # authoritative allow and must route through the fail-closed path below
        # under ``enforce`` (AAASM-4014).
        decision = str(result.get("decision", "") or "").strip().lower()
        reason = str(result.get("reason", "") or "")

        if decision == "deny":
            return {"status": "deny", "reason": reason}
        if decision == "pending":
            return {"status": "pending", "reason": reason}
        if decision in _ERROR_DECISIONS:
            # Native reported it could not reach an authoritative verdict.
            return self._on_query_failure(reason or f"runtime returned {decision}")
        if decision in _ALLOW_DECISIONS:
            return {"status": "allow"}
        # Unknown / empty / missing decision: not an authoritative allow, so fail
        # closed under ``enforce`` (deny) and proceed under observe (fail open),
        # mirroring the error-sentinel handling above (AAASM-4014).
        return self._on_query_failure(reason or f"runtime returned unrecognized decision {decision!r}")

    def _on_query_failure(self, reason: str) -> dict[str, str]:
        """Map an unauthoritative query to deny (enforce) or allow (observe)."""
        if self._enforce:
            return {"status": "deny", "reason": reason}
        return {"status": "allow"}

    def _check_op_control(self, op_id: str | None) -> dict[str, str] | None:
        """Consult the live op-control kill switch for ``op_id`` (AAASM-3491).

        Returns a ``deny`` status dict when the op has been terminated, ``None``
        otherwise — including when no subscriber is wired or no ``op_id`` is
        available, so the call proceeds to the normal runtime query. When the op
        is *paused*, ``await_op`` blocks here until the gateway resumes (or
        terminates) it; this is the cooperative-pause point on the Python tool
        path.
        """
        if self._op_control is None or not op_id:
            return None
        try:
            self._op_control.await_op(op_id)
        except OpTerminatedError as exc:
            return {"status": "deny", "reason": str(exc)}
        return None


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


def _runtime_socket_is_trusted(socket_path: str) -> bool:
    """Whether the default runtime socket is safe to connect to (AAASM-3920).

    The world-traversable ``/tmp`` default path is predictable, so any local
    user could pre-create ``/tmp/aa-runtime-<agent_id>.sock`` to impersonate the
    runtime. As a best-effort pre-connect guard this requires the path to either
    not yet exist (the runtime will bind it) or be a *socket* owned by the
    current user. A foreign-owned file, a non-socket squatting the path, or an
    unstatable path is rejected so :func:`connect_runtime_client` returns
    ``None`` and ``enforce`` mode fails closed instead of talking to an
    attacker-controlled socket.

    This is advisory only. Authoritative peer-credential validation
    (``SO_PEERCRED``) is the Rust ``aa-sdk-client``'s job. On platforms without
    ``os.getuid`` (e.g. Windows) the ownership check is skipped — there is no
    UDS ownership model to assert — and the path is treated as trusted.
    """
    getuid = getattr(os, "getuid", None)
    if getuid is None:
        return True
    try:
        info = os.stat(socket_path)
    except FileNotFoundError:
        # Not created yet: the runtime will bind it. Nothing to distrust.
        return True
    except OSError:
        return False
    if not stat.S_ISSOCK(info.st_mode):
        # A regular file / directory squatting the socket path.
        return False
    # bool() pins the type: getuid is fetched via getattr (typed Any).
    return bool(info.st_uid == getuid())


def connect_runtime_client(agent_id: str) -> Any | None:
    """Connect a native ``RuntimeClient`` to the runtime UDS, or ``None``.

    Returns ``None`` when the native extension is not built, the runtime socket
    is unreachable, or the *default* socket path is squatted by a foreign-owned
    file (AAASM-3920) — all cases mean there is no trusted native fast path to
    register against or query, so a caller under ``enforce`` fails closed. The
    single returned client is reused for both :func:`register_agent` and the
    :class:`RuntimeQueryInterceptor`'s ``query_policy`` calls, so the credential
    token stored by ``register`` is attached to subsequent checks.
    """
    try:
        from agent_assembly._core import RuntimeClient
    except ImportError:
        return None

    socket_path = _resolve_runtime_socket_path(agent_id)
    # Guard only the predictable default path. An explicit AA_RUNTIME_SOCKET
    # override is the operator's trusted topology (e.g. a system-owned socket in
    # a 0700 dir), so it is honoured without the ownership check.
    if not os.environ.get(ENV_RUNTIME_SOCKET) and not _runtime_socket_is_trusted(socket_path):
        return None
    sdk_version = _sdk_version()
    try:
        # Forward the agent identity (signed into the runtime handshake,
        # AAASM-3587) and the installed PyPI package version (signed into the
        # handshake so downgrade detection reflects the real SDK release,
        # AAASM-3683).
        return RuntimeClient.connect(socket_path, agent_id, sdk_version)
    except TypeError:
        # Native build predates the agent_id / sdk_version parameters; fall back
        # to the legacy positional signature so connecting still works against an
        # older core (the version simply is not forwarded).
        try:
            return RuntimeClient.connect(socket_path)
        except Exception:
            return None
    except Exception:
        return None


def _sdk_version() -> str | None:
    """Return the installed ``agent-assembly`` distribution version, or ``None``.

    Prefers ``importlib.metadata.version`` (the authoritative installed-package
    version) and falls back to the in-tree ``agent_assembly.__version__`` when the
    distribution metadata is unavailable (e.g. an editable checkout that was never
    installed). ``None`` lets the native shim fall back to the crate version.
    """
    try:
        return metadata.version("agent-assembly")
    except metadata.PackageNotFoundError:
        try:
            from agent_assembly import __version__

            return __version__
        except Exception:
            return None


def register_agent(
    runtime_client: Any,
    agent_id: str,
    framework: str,
    gateway_endpoint: str | None = None,
    team_id: str | None = None,
    parent_agent_id: str | None = None,
) -> str | None:
    """Register ``agent_id`` with the gateway over the native ``register`` call.

    Delegates to the native ``RuntimeClient.register`` (AAASM-3399), which makes
    the SDK's only direct gateway gRPC call and stores the issued credential
    token on the shared client so later ``query_policy`` checks authenticate
    (ADR 0004 — the SDK never calls core HTTP endpoints directly).

    ``team_id`` and ``parent_agent_id`` carry the agent's lineage/team scoping to
    the gateway (AAASM-3415): ``team_id`` drives team-budget attribution and
    ``parent_agent_id`` the topology graph. They are forwarded to a native build
    that accepts them; an older build (whose ``register`` predates these kwargs)
    is retried with the legacy positional signature so the SDK keeps working
    rather than raising.

    Returns the policy id the gateway assigned, or ``None`` when ``register`` is
    not exposed (older native build). Registration is authoritative: a native
    failure raises ``RuntimeError`` and is allowed to propagate so init surfaces
    a misconfigured gateway rather than silently running unregistered.
    """
    register = getattr(runtime_client, "register", None)
    if register is None:
        return None
    try:
        return str(register(agent_id, agent_id, framework, gateway_endpoint, team_id, parent_agent_id))
    except TypeError:
        # Native build predates the team_id/parent_agent_id parameters
        # (AAASM-3415). Fall back to the legacy signature so registration still
        # succeeds — lineage/team are simply not forwarded against an old core.
        return str(register(agent_id, agent_id, framework, gateway_endpoint))


def _native_core_available() -> bool:
    """Whether the native ``_core`` extension can be imported."""
    try:
        from agent_assembly._core import RuntimeClient  # noqa: F401
    except ImportError:
        return False
    return True


def build_governance_interceptor(
    client: Any,
    agent_id: str,
    enforcement_mode: str | None = None,
    *,
    runtime_client: Any | None = None,
    native_available: bool | None = None,
    op_control: Any | None = None,
) -> Any:
    """Return the interceptor adapters should use for pre-execution checks.

    When a native runtime is reachable, wrap ``client`` in a
    :class:`RuntimeQueryInterceptor` so a runtime ``deny`` actually blocks the
    tool. The failure posture depends on ``enforcement_mode`` (AAASM-3106). The
    ``None`` default is advertised as the gateway's live ``enforce``, so it takes
    the same *local* fail-closed posture as an explicit ``enforce`` (AAASM-4130);
    only ``observe`` / ``disabled`` fail open locally:

    * The native extension is **missing**: return ``client`` unchanged in every
      mode — there is no native authority to fail closed *to*. Under an enforce
      posture this would silently skip the in-process deny, so a loud one-time
      warning is emitted first (AAASM-4130) rather than failing open silently.
    * The native extension is **present** but the runtime socket is unreachable:
      under an enforce posture (``None`` default or explicit ``enforce``) return a
      deny-all :class:`_FailClosedInterceptor`; under ``observe`` / ``disabled``
      return ``client`` unchanged (fail open).

    :param runtime_client: A pre-connected native runtime client (e.g. the one
        :func:`register_agent` registered the token on). When supplied it is
        reused so register and ``query_policy`` share one client; when ``None``
        a fresh connection is established here.
    :param native_available: Whether the native extension is importable. Pass
        this alongside a ``runtime_client`` of ``None`` to distinguish a missing
        extension (fail open in every mode) from an unreachable runtime socket
        (fail closed under enforce). When ``None`` it is detected here.
    """
    enforce = _local_posture_is_enforce(enforcement_mode)

    if runtime_client is None and native_available is None:
        # No caller-supplied client or hint: detect + connect ourselves.
        if not _native_core_available():
            if enforce:
                _warn_sdk_enforcement_unavailable()
            return client
        runtime_client = connect_runtime_client(agent_id)
        native_available = True

    if runtime_client is None:
        # Native missing → no authority to fail closed to, return bare client.
        if not native_available:
            if enforce:
                _warn_sdk_enforcement_unavailable()
            return client
        # Native present but runtime unreachable: deny everything under enforce
        # (fail closed); proceed under observe / disabled (fail open).
        if enforce:
            return _FailClosedInterceptor(client, "runtime unreachable")
        return client

    return RuntimeQueryInterceptor(client, runtime_client, agent_id, enforce=enforce, op_control=op_control)
