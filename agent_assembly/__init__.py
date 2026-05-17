"""Agent Assembly Python SDK."""

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

try:
    from agent_assembly._core import (
        GovernanceEvent,
        PolicyResult,
        PolicyTimeoutError,
        RuntimeClient,
    )
except ImportError:
    pass

__version__ = "0.0.0"

__all__ = [
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

if "RuntimeClient" in globals():
    __all__.extend(
        [
            "RuntimeClient",
            "GovernanceEvent",
            "PolicyResult",
            "PolicyTimeoutError",
        ]
    )
