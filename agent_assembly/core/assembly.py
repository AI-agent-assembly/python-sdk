"""Core assembly initialization module."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Literal, Protocol

from agent_assembly.adapters.base import FrameworkAdapter
from agent_assembly.adapters.langchain.adapter import LangChainAdapter
from agent_assembly.adapters.langchain.runtime import get_active_callback_handler
from agent_assembly.adapters.registry import AdapterRegistry
from agent_assembly.client.gateway import GatewayClient
from agent_assembly.core.gateway_resolver import resolve_api_key, resolve_gateway_url
from agent_assembly.core.runtime_interceptor import (
    _native_core_available,
    build_governance_interceptor,
    connect_runtime_client,
    register_agent,
)
from agent_assembly.core.spawn import _SPAWN_CTX
from agent_assembly.core.transport_security import warn_if_insecure_http_url
from agent_assembly.exceptions import AssemblyError, ConfigurationError

RuntimeMode = Literal["auto", "ebpf", "proxy", "sdk-only"]
NetworkMode = Literal["ebpf", "proxy", "sdk-only"]

EnforcementMode = Literal["enforce", "observe", "disabled"]
"""Posture the governance gateway should apply to this agent's actions.

* ``"enforce"`` — default; deny blocks the action, redact strips secrets.
* ``"observe"`` — dry-run; the gateway records what *would* have happened
  but lets every action through. Surfaced by ``aa audit list --dry-run-only``.
* ``"disabled"`` — policy evaluation skipped entirely. Hermetic test only.

Mirrors ``aa_core::EnforcementMode`` on the wire; uses the same snake_case
tokens the gateway expects in the registration body."""

ENV_GATEWAY_URL = "AA_GATEWAY_URL"
ENV_CONTROL_PLANE_URL = "AA_CONTROL_PLANE_URL"

_DEFAULT_AGENT_ID = "agent-assembly-default"
_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_VALID_RUNTIME_MODES = {"auto", "ebpf", "proxy", "sdk-only"}
_VALID_ENFORCEMENT_MODES: frozenset[EnforcementMode] = frozenset({"enforce", "observe", "disabled"})
_INIT_LOCK = Lock()
_ACTIVE_CONTEXT: AssemblyContext | None = None


def _validate_agent_id(agent_id: str) -> str:
    """Validate agent_id format before it reaches socket-path interpolation (AAASM-4301).

    Only allows [A-Za-z0-9_.-] up to 128 chars. Reject anything else with a clear ValueError
    so callers get a fast, actionable error instead of a downstream FileNotFoundError from
    a malformed socket path.
    """
    if not _AGENT_ID_RE.fullmatch(agent_id):
        raise ValueError(f"invalid agent_id: {agent_id!r}; must match {_AGENT_ID_RE.pattern}")
    return agent_id


class RuntimePatch(Protocol):
    """Internal monkey-patch mechanism used by framework adapters.

    This is the **internal mechanism layer** — not intended for SDK users
    or plugin authors.  Each ``RuntimePatch`` knows how to apply and
    revert a single monkey-patch on a specific framework class or function.

    A ``FrameworkAdapter``'s ``register_hooks()`` creates one or more
    ``RuntimePatch`` instances and calls ``apply()`` on each.  The
    adapter's ``unregister_hooks()`` calls ``revert()`` on each in
    reverse order.

    See Also:
        ``FrameworkAdapter`` in ``adapters/base.py`` — the public adapter
        API with ``register_hooks()`` / ``unregister_hooks()`` methods.
        ADR-0001 (``docs/adr/0001-hook-architecture.md``).
    """

    def apply(self) -> bool: ...

    def revert(self) -> None: ...


@dataclass(slots=True)
class AssemblyContext:
    """Represents an active assembly runtime session."""

    client: GatewayClient
    adapters: list[FrameworkAdapter]
    network_mode: NetworkMode
    _network_shutdown: Callable[[], None]
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _is_shutdown: bool = field(default=False, init=False, repr=False)

    def __enter__(self) -> AssemblyContext:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> Literal[False]:
        del exc_type, exc, tb
        self.shutdown()
        return False

    @property
    def is_shutdown(self) -> bool:
        with self._lock:
            return self._is_shutdown

    def shutdown(self) -> None:
        shutdown_errors: list[str] = []
        should_clear_active_context = False
        with self._lock:
            if self._is_shutdown:
                return None

            try:
                self._network_shutdown()
            except Exception as error:  # pragma: no cover - defensive guard
                shutdown_errors.append(f"network shutdown failed: {error}")

            for adapter in reversed(self.adapters):
                try:
                    adapter.unregister_hooks()
                except Exception as error:  # pragma: no cover - defensive guard
                    shutdown_errors.append(f"adapter hook removal failed: {error}")

            try:
                self.client.close()
            except Exception as error:  # pragma: no cover - defensive guard
                shutdown_errors.append(f"client close failed: {error}")

            self._is_shutdown = True
            should_clear_active_context = True

        if should_clear_active_context:
            _clear_active_context(self)
        if shutdown_errors:
            raise AssemblyError("; ".join(shutdown_errors))


def init_assembly(
    gateway_url: str | None = None,
    api_key: str | None = None,
    agent_id: str | None = None,
    mode: RuntimeMode = "auto",
    *,
    control_plane_url: str | None = None,
    parent_agent_id: str | None = None,
    team_id: str | None = None,
    delegation_reason: str | None = None,
    spawned_by_tool: str | None = None,
    depth: int | None = None,
    enforcement_mode: EnforcementMode | None = None,
) -> AssemblyContext:
    """Initialize the Agent Assembly SDK runtime for this process.

    Uses ``AdapterRegistry.get_available_adapters_by_priority()`` as the
    single detection path for framework adapters (see ADR-0001).

    With no ``gateway_url`` / ``api_key`` arguments the SDK falls back
    through the resolver chain (env → config file → local default with
    optional auto-start) per Epic 17 S-G — see
    ``agent_assembly.core.gateway_resolver``.

    Agent registration and the pre-execution policy check go through the native
    ``aa-sdk-client`` shim to the core over gRPC/UDS (ADR 0004): ``init_assembly``
    registers the agent on startup (storing the issued credential token on the
    native client) and a tool call is checked via the native ``query_policy`` so
    a ``deny`` blocks the tool before it runs. The SDK never calls a core HTTP
    endpoint directly for registration or policy checks.

    :param control_plane_url: Optional URL of the control-plane HTTP API. When
        supplied, the SDK issues its remaining HTTP routes (topology edges,
        secret dispatch) against it instead of ``gateway_url``. When omitted it
        falls back to ``gateway_url`` — the backwards-compatible single-host OSS
        dev setup. Resolution order: explicit kwarg > ``AA_CONTROL_PLANE_URL``
        env-var > unset (falls back to ``gateway_url``).
    :param enforcement_mode: Per-agent governance posture applied to this
        agent's actions (see :data:`EnforcementMode`). Defaults to ``None``,
        which lets the gateway apply its server-side default (live ``enforce``).
        Because that default is ``enforce``, the SDK's *local* pre-execution
        fast path also takes the fail-closed posture under ``None`` (AAASM-4130):
        with the native runtime present an unreachable socket or an
        unauthoritative ``query_policy`` **denies** rather than silently
        proceeding, and on a pure-Python install (native extension absent) a loud
        one-time warning is emitted because no in-process deny can run — the
        gateway / proxy / eBPF layers remain authoritative, so init stays graceful
        and never hard-fails on a missing runtime. Pass ``"observe"`` to register
        the agent in dry-run / sandbox mode: every action proceeds (local checks
        fail open) and the gateway records would-be violations as shadow audit
        events.
    """
    gateway_url = resolve_gateway_url(gateway_url)
    api_key = resolve_api_key(api_key)
    # Warn early when the resolved gateway would carry the Bearer API key over
    # plaintext http:// to a non-loopback host (AAASM-3725). The control-plane
    # URL is the host the credential is actually sent to when set.
    warn_if_insecure_http_url(control_plane_url or gateway_url, has_api_key=bool(api_key))
    gateway_url, control_plane_url = _validate_inputs(
        gateway_url=gateway_url,
        mode=mode,
        control_plane_url=control_plane_url,
        enforcement_mode=enforcement_mode,
    )
    if delegation_reason is not None and len(delegation_reason) > 256:
        raise ValueError("delegation_reason must be <= 256 characters")

    # Auto-fill lineage from ambient spawn context when not passed explicitly.
    _spawn = _SPAWN_CTX.get()
    if _spawn is not None:
        if parent_agent_id is None:
            parent_agent_id = _spawn.parent_agent_id
        if depth is None:
            depth = _spawn.depth
        if spawned_by_tool is None:
            spawned_by_tool = _spawn.spawned_by_tool

    resolved_agent_id = _validate_agent_id(agent_id or _DEFAULT_AGENT_ID)

    global _ACTIVE_CONTEXT
    with _INIT_LOCK:
        if _ACTIVE_CONTEXT is not None and not _ACTIVE_CONTEXT.is_shutdown:
            _validate_active_context_compatibility(
                _ACTIVE_CONTEXT,
                gateway_url=gateway_url,
                api_key=api_key,
                agent_id=resolved_agent_id,
            )
            return _ACTIVE_CONTEXT

        client = GatewayClient(
            gateway_url=gateway_url,
            agent_id=resolved_agent_id,
            api_key=api_key,
            control_plane_url=control_plane_url,
            parent_agent_id=parent_agent_id,
            team_id=team_id,
            delegation_reason=delegation_reason,
            spawned_by_tool=spawned_by_tool,
            depth=depth,
            enforcement_mode=enforcement_mode,
        )

        registered_adapters: list[FrameworkAdapter] = []
        network_mode: NetworkMode = "sdk-only"
        network_shutdown: Callable[[], None] = _noop_shutdown
        try:
            native_available = _native_core_available()
            runtime_client = connect_runtime_client(resolved_agent_id) if native_available else None
            _register_agent_with_gateway(
                runtime_client=runtime_client,
                agent_id=resolved_agent_id,
                enforcement_mode=enforcement_mode,
                team_id=team_id,
                parent_agent_id=parent_agent_id,
            )
            registered_adapters = _register_adapters(
                client=client,
                process_agent_id=resolved_agent_id,
                enforcement_mode=enforcement_mode,
                runtime_client=runtime_client,
                native_available=native_available,
            )
            network_mode, network_shutdown = _start_network_layer(client=client, mode=mode)
        except Exception as error:
            _unregister_adapters(registered_adapters)
            client.close()
            raise ConfigurationError(f"Failed to initialize assembly runtime: {error}") from error

        context = AssemblyContext(
            client=client,
            adapters=registered_adapters,
            network_mode=network_mode,
            _network_shutdown=network_shutdown,
        )
        _ACTIVE_CONTEXT = context
        return context


def _validate_inputs(
    *,
    gateway_url: str,
    mode: RuntimeMode,
    control_plane_url: str | None = None,
    enforcement_mode: EnforcementMode | None = None,
) -> tuple[str, str | None]:
    """Validate inputs and apply env-var fallbacks.

    Resolution order for each URL is explicit kwarg > env-var > unset:
    ``gateway_url`` falls back to ``AA_GATEWAY_URL`` and ``control_plane_url``
    falls back to ``AA_CONTROL_PLANE_URL``. Returns the resolved
    ``(gateway_url, control_plane_url)`` pair.
    """
    if not gateway_url:
        gateway_url = os.environ.get(ENV_GATEWAY_URL, "")
    if control_plane_url is None:
        control_plane_url = os.environ.get(ENV_CONTROL_PLANE_URL) or None

    if not gateway_url:
        raise ConfigurationError("gateway_url is required")
    if mode not in _VALID_RUNTIME_MODES:
        raise ConfigurationError("mode must be one of: auto, ebpf, proxy, sdk-only")
    if enforcement_mode is not None and enforcement_mode not in _VALID_ENFORCEMENT_MODES:
        raise ConfigurationError(
            f"enforcement_mode must be one of: enforce, observe, disabled (got: {enforcement_mode!r})"
        )
    return gateway_url, control_plane_url


def _register_agent_with_gateway(
    *,
    runtime_client: Any | None,
    agent_id: str,
    enforcement_mode: EnforcementMode | None,
    team_id: str | None = None,
    parent_agent_id: str | None = None,
) -> None:
    """Register the agent with the gateway over the native gRPC ``register``.

    Registration goes through the native runtime client (AAASM-3399) so the
    issued credential token is stored on the same client the
    ``RuntimeQueryInterceptor`` later uses for ``query_policy`` — the SDK never
    calls a core HTTP endpoint directly (ADR 0004).

    ``team_id`` and ``parent_agent_id`` are forwarded to the native register so
    the gateway gets the agent's team-budget scoping and topology lineage on the
    native path, restoring what the legacy REST register sent (AAASM-3415).

    No native runtime (extension missing or socket unreachable) means there is
    nothing to register against: the call is skipped. Under ``enforce`` a native
    registration failure propagates so a misconfigured gateway surfaces at init;
    under ``observe`` / ``disabled`` (or no mode) it is swallowed so the dry-run
    / hermetic-test layer never hard-fails on registration.
    """
    if runtime_client is None:
        return
    framework = "python"
    try:
        register_agent(
            runtime_client,
            agent_id,
            framework,
            team_id=team_id,
            parent_agent_id=parent_agent_id,
        )
    except Exception:
        if enforcement_mode == "enforce":
            raise


def _register_adapters(
    client: GatewayClient,
    process_agent_id: str,
    enforcement_mode: EnforcementMode | None = None,
    runtime_client: Any | None = None,
    native_available: bool = False,
) -> list[FrameworkAdapter]:
    """Detect available frameworks via AdapterRegistry and register hooks.

    Adapters are returned in priority order.  LangChain is registered first
    so its ``AssemblyCallbackHandler`` can thread through to subsequent
    adapters as the governance interceptor.

    When the native runtime is reachable, the bare ``GatewayClient`` is wrapped
    in a ``RuntimeQueryInterceptor`` so a runtime ``deny`` blocks the tool via
    ``check_tool_start``. ``enforcement_mode`` decides the failure posture: under
    ``enforce`` an unreachable runtime or a failed query blocks (fail closed,
    AAASM-3106); under ``observe`` / ``disabled`` it proceeds (fail open).
    """
    registry = AdapterRegistry()
    adapters = registry.get_available_adapters_by_priority()

    registered: list[FrameworkAdapter] = []
    interceptor: Any = build_governance_interceptor(
        client,
        process_agent_id,
        enforcement_mode,
        runtime_client=runtime_client,
        native_available=native_available,
    )

    for adapter in adapters:
        adapter.set_process_agent_id(process_agent_id)

        try:
            adapter.register_hooks(interceptor)
        except Exception:
            continue

        registered.append(adapter)

        # After LangChain registers, its callback handler becomes the
        # interceptor for all subsequent adapters.
        if isinstance(adapter, LangChainAdapter):
            callback_handler = get_active_callback_handler()
            if callback_handler is not None:
                interceptor = callback_handler

    return registered


def _unregister_adapters(adapters: list[FrameworkAdapter]) -> None:
    for adapter in reversed(adapters):
        try:
            adapter.unregister_hooks()
        except Exception:
            continue


def _start_network_layer(*, client: GatewayClient, mode: RuntimeMode) -> tuple[NetworkMode, Callable[[], None]]:
    if mode == "sdk-only":
        return "sdk-only", _noop_shutdown

    if mode == "ebpf":
        if not _platform_supports_ebpf():
            raise ConfigurationError("eBPF mode is not supported on this platform.")
        return "ebpf", _start_ebpf_probes(client)

    if mode == "proxy":
        return "proxy", _start_mitm_proxy(client)

    if _platform_supports_ebpf():
        return "ebpf", _start_ebpf_probes(client)
    return "proxy", _start_mitm_proxy(client)


def _platform_supports_ebpf() -> bool:
    return sys.platform.startswith("linux")


def _start_ebpf_probes(client: GatewayClient) -> Callable[[], None]:
    del client
    return _noop_shutdown


def _start_mitm_proxy(client: GatewayClient) -> Callable[[], None]:
    del client
    return _noop_shutdown


def _noop_shutdown() -> None:
    return None


def _clear_active_context(context: AssemblyContext) -> None:
    global _ACTIVE_CONTEXT
    with _INIT_LOCK:
        if _ACTIVE_CONTEXT is context:
            _ACTIVE_CONTEXT = None


def _validate_active_context_compatibility(
    context: AssemblyContext,
    *,
    gateway_url: str,
    api_key: str,
    agent_id: str,
) -> None:
    if context.client.gateway_url != gateway_url.rstrip("/"):
        raise ConfigurationError("init_assembly already initialized with a different gateway_url.")
    if context.client.api_key != api_key:
        raise ConfigurationError("init_assembly already initialized with a different api_key.")
    if context.client.agent_id != agent_id:
        raise ConfigurationError("init_assembly already initialized with a different agent_id.")
