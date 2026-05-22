"""Install-time runtime binary resolution for the agent-assembly Python SDK.

This module is the lean, blocking presence check for the ``aasm`` sidecar
binary. It is intentionally separate from :mod:`agent_assembly.runtime`,
which manages the full lifecycle (port probe + subprocess spawn). The
intended use is at import time or at the start of long-running scripts:
fail fast with a clear install hint when the binary is unavailable, before
the user discovers it via a subtle subprocess failure deep in the SDK call.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "BINARY_NAME",
    "INSTALL_HINT",
    "WHEEL_BUNDLED_BIN",
]

BINARY_NAME = "aasm"

# Path where the platform-wheel ([runtime] extra) bundles the sidecar binary.
# Mirrors the location runtime.py's find_aasm_binary() also searches, so
# both modules observe the same wheel artifact without coordination.
WHEEL_BUNDLED_BIN = Path(__file__).resolve().parent / "bin" / BINARY_NAME

INSTALL_HINT = (
    "agent-assembly runtime binary `aasm` was not found.\n"
    "  Install the platform wheel: pip install agent-assembly[runtime]\n"
    "  Or install manually:        brew install agent-assembly/tap/aasm\n"
    "                              curl -fsSL https://get.agent-assembly.io | sh"
)
