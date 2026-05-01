"""
Type definitions for the Agent Assembly Python SDK.

This module provides centralized type aliases and type definitions following
PEP 561, PEP 484, PEP 585, and PEP 695 standards for static type checking with MyPy.

Type aliases use the modern `type` statement (PEP 695) introduced in Python 3.12,
which provides better type inference and cleaner syntax compared to TypeAlias.

Type Hierarchy:
    - Agent types: Agent identity and configuration types
    - Policy types: Policy enforcement and governance types
    - Event types: Audit logging and event handling types
    - Gateway types: Communication with governance gateway
"""

from __future__ import annotations

__all__ = [
    "AgentId",
    "PolicyId",
    "AssemblyId",
    "ConfigDict",
]
