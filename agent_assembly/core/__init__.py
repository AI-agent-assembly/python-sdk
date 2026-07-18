"""Core module for Agent Assembly initialization."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_assembly.core.assembly import (
        ENFORCEMENT_MODES,
        AssemblyContext,
        init_assembly,
    )
    from agent_assembly.core.lineage import LineageRegistry

__all__ = ["init_assembly", "AssemblyContext", "ENFORCEMENT_MODES", "LineageRegistry"]


def __getattr__(name: str) -> Any:
    if name in ("AssemblyContext", "init_assembly", "ENFORCEMENT_MODES"):
        from agent_assembly.core.assembly import (  # noqa: PLC0415
            ENFORCEMENT_MODES,
            AssemblyContext,
            init_assembly,
        )

        globals()["AssemblyContext"] = AssemblyContext
        globals()["init_assembly"] = init_assembly
        globals()["ENFORCEMENT_MODES"] = ENFORCEMENT_MODES
        return globals()[name]
    if name == "LineageRegistry":
        from agent_assembly.core.lineage import LineageRegistry  # noqa: PLC0415

        globals()["LineageRegistry"] = LineageRegistry
        return LineageRegistry
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
