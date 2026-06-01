"""Agent Assembly Python SDK."""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import sys
from typing import TYPE_CHECKING, Any

__version__ = "0.0.1a3"

# AAASM-1696: top-level exports are resolved lazily so that lightweight
# submodules (e.g. `agent_assembly.runtime`, which is stdlib-only) can be
# imported without dragging in the SDK's third-party dependency surface
# (`httpx`, `pydantic`, …). See PEP 562.
_LAZY_EXPORTS: dict[str, str] = {
    "init_assembly": "agent_assembly.core",
    "AssemblyContext": "agent_assembly.core",
    "GovernanceInterceptor": "agent_assembly.adapters",
    "FrameworkAdapter": "agent_assembly.adapters",
    "AssemblyError": "agent_assembly.exceptions",
    "AgentError": "agent_assembly.exceptions",
    "PolicyError": "agent_assembly.exceptions",
    "GatewayError": "agent_assembly.exceptions",
    "ConfigurationError": "agent_assembly.exceptions",
    "AdapterValidationError": "agent_assembly.exceptions",
    "ToolExecutionBlockedError": "agent_assembly.exceptions",
    "MCPToolBlockedError": "agent_assembly.exceptions",
    "AuditEvent": "agent_assembly.types",
    "CallStackNode": "agent_assembly.types",
    "CallStackNodeKind": "agent_assembly.types",
    "GovernanceEvent": "agent_assembly._core",
    "PolicyResult": "agent_assembly._core",
    "PolicyTimeoutError": "agent_assembly._core",
    "RuntimeClient": "agent_assembly._core",
}

_ALWAYS_EXPORTED: list[str] = [
    "__version__",
    "init_assembly",
    "AssemblyContext",
    "GovernanceInterceptor",
    "FrameworkAdapter",
    "AssemblyError",
    "AgentError",
    "PolicyError",
    "GatewayError",
    "ConfigurationError",
    "AdapterValidationError",
    "ToolExecutionBlockedError",
    "MCPToolBlockedError",
    "AuditEvent",
    "CallStackNode",
    "CallStackNodeKind",
]

_OPTIONAL_CORE: list[str] = [
    "RuntimeClient",
    "GovernanceEvent",
    "PolicyResult",
    "PolicyTimeoutError",
]


def _core_available() -> bool:
    if "agent_assembly._core" in sys.modules:
        return True
    try:
        return importlib.util.find_spec("agent_assembly._core") is not None
    except (ModuleNotFoundError, ValueError):
        return False


__all__: list[str] = list(_ALWAYS_EXPORTED)
if _core_available():
    __all__.extend(_OPTIONAL_CORE)


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module 'agent_assembly' has no attribute {name!r}")
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        if module_name == "agent_assembly._core":
            raise AttributeError(
                f"module 'agent_assembly' has no attribute {name!r}: the native '_core' extension is not built"
            ) from None
        raise
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(globals()))


if TYPE_CHECKING:
    from agent_assembly.adapters import FrameworkAdapter, GovernanceInterceptor
    from agent_assembly.core import AssemblyContext, init_assembly
    from agent_assembly.exceptions import (
        AdapterValidationError,
        AgentError,
        AssemblyError,
        ConfigurationError,
        GatewayError,
        MCPToolBlockedError,
        PolicyError,
        ToolExecutionBlockedError,
    )
    from agent_assembly.types import AuditEvent, CallStackNode, CallStackNodeKind

    with contextlib.suppress(ImportError):
        from agent_assembly._core import (
            GovernanceEvent,
            PolicyResult,
            PolicyTimeoutError,
            RuntimeClient,
        )
