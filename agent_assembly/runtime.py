"""Runtime auto-detection and lifecycle management for the `aasm` sidecar (F115 / AAASM-1205).

The `init_assembly()` exported here is intentionally NOT re-exported from
`agent_assembly` at the top level: the existing gateway-based
`agent_assembly.init_assembly` keeps its meaning. Opt in to the runtime-managed
flow with ``from agent_assembly.runtime import init_assembly``.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "BINARY_NAME",
    "DEFAULT_PORT",
    "DEFAULT_RUNTIME_HOST",
    "INSTALL_HINT",
]

BINARY_NAME = "aasm"
DEFAULT_PORT = 7878
DEFAULT_RUNTIME_HOST = "127.0.0.1"

USER_LOCAL_BIN = Path.home() / ".local" / "bin"
WHEEL_BUNDLED_BIN = Path(__file__).resolve().parent / "bin"
DOCKER_BASE_BIN = Path("/usr/local/bin")

RUNTIME_LOG_FILENAME = ".aasm-runtime.log"

INSTALL_HINT = (
    "agent-assembly runtime not found.\n"
    "  Install with: pip install agent-assembly-python[runtime]\n"
    "  Or manually:  brew install agent-assembly/tap/aasm\n"
    "               curl -fsSL https://get.agent-assembly.io | sh"
)
