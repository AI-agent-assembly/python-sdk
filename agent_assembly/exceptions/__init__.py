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
