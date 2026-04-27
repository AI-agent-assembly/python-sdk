"""Exception hierarchy for SDK errors."""

from __future__ import annotations

__all__ = [
    "AssemblyError",
    "AgentError",
    "PolicyError",
    "GatewayError",
    "ConfigurationError",
    "AdapterValidationError",
]


class AssemblyError(Exception):
    """Base exception for Agent Assembly SDK errors."""
    pass


class AgentError(AssemblyError):
    """Exception raised for agent-related errors."""
    pass


class PolicyError(AssemblyError):
    """Exception raised for policy-related errors."""
    pass


class GatewayError(AssemblyError):
    """Exception raised for gateway communication errors."""
    pass


class ConfigurationError(AssemblyError):
    """Exception raised for configuration errors."""
    pass


class AdapterValidationError(AssemblyError):
    """Exception raised when an adapter contract is invalid."""
    pass
