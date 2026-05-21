"""Exception hierarchy for SDK errors."""

from __future__ import annotations

__all__ = [
    "AssemblyError",
    "AgentError",
    "PolicyError",
    "GatewayError",
    "ConfigurationError",
    "AdapterValidationError",
    "ToolExecutionBlockedError",
    "MCPToolBlockedError",
    "PolicyViolationError",
    "OpTerminatedError",
]


class AssemblyError(Exception):
    """Base exception for Agent Assembly SDK errors."""


class AgentError(AssemblyError):
    """Exception raised for agent-related errors."""


class PolicyError(AssemblyError):
    """Exception raised for policy-related errors."""


class GatewayError(AssemblyError):
    """Exception raised for gateway communication errors."""


class ConfigurationError(AssemblyError):
    """Exception raised for configuration errors."""


class AdapterValidationError(AssemblyError):
    """Exception raised when an adapter contract is invalid."""


class ToolExecutionBlockedError(AssemblyError):
    """Exception raised when a tool run is blocked by governance."""


class MCPToolBlockedError(ToolExecutionBlockedError):
    """Exception raised when an MCP tool call is blocked by governance."""

    def __init__(
        self,
        message: str,
        *,
        tool_name: str | None = None,
        server: str | None = None,
    ) -> None:
        super().__init__(message)
        self.tool_name = tool_name
        self.server = server


class PolicyViolationError(ToolExecutionBlockedError):
    """Exception raised when policy blocks tool execution."""


class OpTerminatedError(AssemblyError):
    """Raised when the gateway terminates an in-flight op (AAASM-1422 PR-E).

    Carries the originating `op_id` so callers can correlate the failure
    against the operation they were awaiting. Surfaced by
    `OpControlSubscriber.await_op` when an `OP_CONTROL_SIGNAL_TERMINATE`
    arrives for the awaited op.
    """

    def __init__(self, message: str, *, op_id: str) -> None:
        super().__init__(message)
        self.op_id = op_id
