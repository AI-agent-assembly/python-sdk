"""Agent Assembly Python SDK."""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import sys
from typing import TYPE_CHECKING, Any

__version__ = "0.0.1rc1"

_MODULE_CORE = "agent_assembly.core"
_MODULE_ADAPTERS = "agent_assembly.adapters"
_MODULE_EXCEPTIONS = "agent_assembly.exceptions"
_MODULE_TYPES = "agent_assembly.types"
_MODULE_NATIVE_CORE = "agent_assembly._core"

# AAASM-1696: top-level exports are resolved lazily so that lightweight
# submodules (e.g. `agent_assembly.runtime`, which is stdlib-only) can be
# imported without dragging in the SDK's third-party dependency surface
# (`httpx`, `pydantic`, …). See PEP 562.
_LAZY_EXPORTS: dict[str, str] = {
    "init_assembly": _MODULE_CORE,
    "AssemblyContext": _MODULE_CORE,
    "GovernanceInterceptor": _MODULE_ADAPTERS,
    "FrameworkAdapter": _MODULE_ADAPTERS,
    "AssemblyError": _MODULE_EXCEPTIONS,
    "AgentError": _MODULE_EXCEPTIONS,
    "PolicyError": _MODULE_EXCEPTIONS,
    "GatewayError": _MODULE_EXCEPTIONS,
    "ConfigurationError": _MODULE_EXCEPTIONS,
    "AdapterValidationError": _MODULE_EXCEPTIONS,
    "ToolExecutionBlockedError": _MODULE_EXCEPTIONS,
    "MCPToolBlockedError": _MODULE_EXCEPTIONS,
    "AuditEvent": _MODULE_TYPES,
    "CallStackNode": _MODULE_TYPES,
    "CallStackNodeKind": _MODULE_TYPES,
    "GovernanceEvent": _MODULE_NATIVE_CORE,
    "RuntimeClient": _MODULE_NATIVE_CORE,
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
]


def _core_available() -> bool:
    if _MODULE_NATIVE_CORE in sys.modules:
        return True
    try:
        return importlib.util.find_spec(_MODULE_NATIVE_CORE) is not None
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
        if module_name == _MODULE_NATIVE_CORE:
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
    from agent_assembly.adapters import FrameworkAdapter as FrameworkAdapter
    from agent_assembly.adapters import GovernanceInterceptor as GovernanceInterceptor
    from agent_assembly.core import AssemblyContext as AssemblyContext
    from agent_assembly.core import init_assembly as init_assembly
    from agent_assembly.exceptions import (
        AdapterValidationError as AdapterValidationError,
    )
    from agent_assembly.exceptions import AgentError as AgentError
    from agent_assembly.exceptions import AssemblyError as AssemblyError
    from agent_assembly.exceptions import ConfigurationError as ConfigurationError
    from agent_assembly.exceptions import GatewayError as GatewayError
    from agent_assembly.exceptions import MCPToolBlockedError as MCPToolBlockedError
    from agent_assembly.exceptions import PolicyError as PolicyError
    from agent_assembly.exceptions import (
        ToolExecutionBlockedError as ToolExecutionBlockedError,
    )
    from agent_assembly.types import AuditEvent as AuditEvent
    from agent_assembly.types import CallStackNode as CallStackNode
    from agent_assembly.types import CallStackNodeKind as CallStackNodeKind

    with contextlib.suppress(ImportError):
        from agent_assembly._core import GovernanceEvent as GovernanceEvent
        from agent_assembly._core import RuntimeClient as RuntimeClient
