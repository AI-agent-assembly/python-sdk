"""Core assembly initialization module."""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
import sys
from threading import Lock
from typing import Any, Callable, Literal, Protocol

from agent_assembly.adapters.crewai.patch import CrewAIPatch
from agent_assembly.adapters.langchain.patch import LangChainPatch
from agent_assembly.adapters.langchain.runtime import get_active_callback_handler
from agent_assembly.adapters.langgraph import LangGraphPatch
from agent_assembly.adapters.mcp import MCPClientPatch
from agent_assembly.adapters.openai_agents import OpenAIAgentsPatch
from agent_assembly.adapters.pydantic_ai.patch import PydanticAIPatch
from agent_assembly.client.gateway import GatewayClient
from agent_assembly.exceptions import AssemblyError, ConfigurationError

RuntimeMode = Literal["auto", "ebpf", "proxy", "sdk-only"]
NetworkMode = Literal["ebpf", "proxy", "sdk-only"]

_DEFAULT_AGENT_ID = "agent-assembly-default"
_VALID_RUNTIME_MODES = {"auto", "ebpf", "proxy", "sdk-only"}
_INIT_LOCK = Lock()
_ACTIVE_CONTEXT: AssemblyContext | None = None


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
    patches: list[RuntimePatch]
    network_mode: NetworkMode
    _network_shutdown: Callable[[], None]
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _is_shutdown: bool = field(default=False, init=False, repr=False)

    def __enter__(self) -> AssemblyContext:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
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

            for patch in reversed(self.patches):
                try:
                    patch.revert()
                except Exception as error:  # pragma: no cover - defensive guard
                    shutdown_errors.append(f"patch revert failed: {error}")

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
    gateway_url: str,
    api_key: str,
    agent_id: str | None = None,
    mode: RuntimeMode = "auto",
    **kwargs: Any,
) -> AssemblyContext:
    """Initialize the Agent Assembly SDK runtime for this process."""
    del kwargs
    _validate_inputs(gateway_url=gateway_url, api_key=api_key, mode=mode)
    resolved_agent_id = agent_id or _DEFAULT_AGENT_ID

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
        )

        patches: list[RuntimePatch] = []
        network_mode: NetworkMode = "sdk-only"
        network_shutdown: Callable[[], None] = _noop_shutdown
        try:
            patches = _apply_runtime_patches(
                client=client,
                process_agent_id=resolved_agent_id,
            )
            network_mode, network_shutdown = _start_network_layer(client=client, mode=mode)
        except Exception as error:
            _revert_patches(patches)
            client.close()
            raise ConfigurationError(f"Failed to initialize assembly runtime: {error}") from error

        context = AssemblyContext(
            client=client,
            patches=patches,
            network_mode=network_mode,
            _network_shutdown=network_shutdown,
        )
        _ACTIVE_CONTEXT = context
        return context


def _validate_inputs(*, gateway_url: str, api_key: str, mode: RuntimeMode) -> None:
    if not gateway_url:
        raise ConfigurationError("gateway_url is required")
    if not api_key:
        raise ConfigurationError("api_key is required")
    if mode not in _VALID_RUNTIME_MODES:
        raise ConfigurationError(
            "mode must be one of: auto, ebpf, proxy, sdk-only"
        )


def _is_installed(package: str) -> bool:
    """Check if a package is importable without importing it."""
    try:
        return importlib.util.find_spec(package) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _has_agents_sdk() -> bool:
    """Check specifically for openai.agents module (not just openai base)."""
    return _is_installed("openai.agents")


def _build_patch_plan(client: GatewayClient, process_agent_id: str) -> list[RuntimePatch]:
    patch_plan: list[RuntimePatch] = []
    langchain_installed = _is_installed("langchain")
    langgraph_installed = _is_installed("langgraph")
    callback_target: Any = client

    if langchain_installed or langgraph_installed:
        patch_plan.append(LangChainPatch(client, process_agent_id=process_agent_id))
        callback_handler = get_active_callback_handler()
        if callback_handler is not None:
            callback_target = callback_handler

    if langgraph_installed:
        patch_plan.append(LangGraphPatch(callback_target))

    if _is_installed("crewai"):
        patch_plan.append(CrewAIPatch(callback_target))
    if _is_installed("pydantic_ai"):
        patch_plan.append(PydanticAIPatch(callback_target))
    if _is_installed("openai") and _has_agents_sdk():
        patch_plan.append(
            OpenAIAgentsPatch(
                callback_handler=callback_target,
                process_agent_id=process_agent_id,
            )
        )
    if _is_installed("mcp"):
        # Keep MCP patch last as fallback for remaining tool dispatch paths.
        patch_plan.append(
            MCPClientPatch(
                callback_handler=callback_target,
                process_agent_id=process_agent_id,
            )
        )

    return patch_plan


def _apply_runtime_patches(client: GatewayClient, process_agent_id: str) -> list[RuntimePatch]:
    applied: list[RuntimePatch] = []
    patch_plan = _build_patch_plan(client=client, process_agent_id=process_agent_id)
    for index, patch in enumerate(patch_plan):
        if patch.apply():
            applied.append(patch)
            callback_handler = get_active_callback_handler()
            if callback_handler is not None:
                _replace_callback_targets(patch_plan[index + 1 :], callback_handler)
    return applied


def _revert_patches(patches: list[RuntimePatch]) -> None:
    for patch in reversed(patches):
        try:
            patch.revert()
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


def _replace_callback_targets(patches: list[RuntimePatch], callback_handler: Any) -> None:
    for patch in patches:
        if hasattr(patch, "callback_handler"):
            setattr(patch, "callback_handler", callback_handler)


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
