"""Install-time runtime binary resolution for the agent-assembly Python SDK.

This module is the lean, blocking presence check for the ``aasm`` sidecar
binary. It is intentionally separate from :mod:`agent_assembly.runtime`,
which manages the full lifecycle (port probe + subprocess spawn). The
intended use is at import time or at the start of long-running scripts:
fail fast with a clear install hint when the binary is unavailable, before
the user discovers it via a subtle subprocess failure deep in the SDK call.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

__all__ = [
    "BINARY_NAME",
    "INSTALL_HINT",
    "WHEEL_BUNDLED_BIN",
    "ensure_runtime",
]

BINARY_NAME = "aasm"

# Path where the platform-wheel ([runtime] extra) bundles the sidecar binary.
# Mirrors the location runtime.py's find_aasm_binary() also searches, so
# both modules observe the same wheel artifact without coordination.
WHEEL_BUNDLED_BIN = Path(__file__).resolve().parent / "bin" / BINARY_NAME

INSTALL_HINT = (
    "agent-assembly runtime binary `aasm` was not found.\n"
    "  Install the platform wheel: pip install agent-assembly[runtime]\n"
    "  Or install manually:        brew install ai-agent-assembly/tap/aasm\n"
    "                              curl -fsSL https://get.agent-assembly.io | sh"
)


def ensure_runtime() -> Path:
    """Return the resolved path to the ``aasm`` sidecar binary.

    Search order, fast to slow:

    1. ``$PATH`` (Homebrew tap, ``cargo install``, ``curl`` installer default).
    2. ``agent_assembly/bin/aasm`` bundled by the ``[runtime]`` platform wheel.

    Raises:
        RuntimeError: when no binary is found on either path. The message
            carries :data:`INSTALL_HINT` with copy-paste install commands.
    """
    path_hit = shutil.which(BINARY_NAME)
    if path_hit:
        return Path(path_hit)
    if WHEEL_BUNDLED_BIN.is_file() and os.access(WHEEL_BUNDLED_BIN, os.X_OK):
        return WHEEL_BUNDLED_BIN
    raise RuntimeError(INSTALL_HINT)
