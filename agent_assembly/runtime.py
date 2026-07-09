"""Runtime auto-detection and lifecycle management for the `aasm` sidecar (F115 / AAASM-1205).

The `init_assembly()` exported here is intentionally NOT re-exported from
`agent_assembly` at the top level: the existing gateway-based
`agent_assembly.init_assembly` keeps its meaning. Opt in to the runtime-managed
flow with ``from agent_assembly.runtime import init_assembly``.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path

__all__ = [
    "BINARY_NAME",
    "DEFAULT_PORT",
    "DEFAULT_RUNTIME_HOST",
    "INSTALL_HINT",
    "find_aasm_binary",
    "init_assembly",
    "is_running",
    "start_runtime",
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
    "  Install with: pip install --pre agent-assembly[runtime]\n"
    "  Or manually:  brew install ai-agent-assembly/tap/aasm\n"
    "               curl -fsSL https://agent-assembly.com/install.sh | sh"
)


def find_aasm_binary() -> Path | None:
    """Locate the `aasm` binary across the 5 supported install paths.

    Search order: ``$PATH`` (covers Homebrew and ``cargo install``) →
    ``~/.local/bin/aasm`` (curl installer default) →
    ``agent_assembly/bin/aasm`` (wheel-bundled with the ``[runtime]`` extra) →
    ``/usr/local/bin/aasm`` (Docker base image). Returns the first executable
    match, or ``None`` when no candidate exists.
    """
    path_hit = shutil.which(BINARY_NAME)
    if path_hit:
        return Path(path_hit)
    for candidate in (
        USER_LOCAL_BIN / BINARY_NAME,
        WHEEL_BUNDLED_BIN / BINARY_NAME,
        DOCKER_BASE_BIN / BINARY_NAME,
    ):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def is_running(port: int = DEFAULT_PORT, *, host: str = DEFAULT_RUNTIME_HOST) -> bool:
    """Return True iff a local TCP listener accepts a connect on ``host:port``.

    A 100 ms connect window keeps the probe cheap on the common idle path; any
    socket error (refused, timeout, unreachable) is treated as no-sidecar.
    """
    try:
        with socket.create_connection((host, port), timeout=0.1):
            return True
    except OSError:
        return False


def start_runtime(
    binary: Path,
    *,
    port: int = DEFAULT_PORT,
    log_dir: Path | None = None,
) -> subprocess.Popen[bytes]:
    """Spawn ``aasm serve --port <port>`` as a detached background subprocess.

    Stdout and stderr are appended to ``<log_dir>/.aasm-runtime.log`` (default
    log directory is the current working directory) so the sidecar outlives
    the parent. ``start_new_session=True`` detaches the child from this
    process's controlling terminal.
    """
    target_dir = log_dir if log_dir is not None else Path.cwd()
    log_path = target_dir / RUNTIME_LOG_FILENAME
    log_file = log_path.open("ab")
    return subprocess.Popen(
        [str(binary), "serve", "--port", str(port)],
        stdout=log_file,
        stderr=log_file,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def init_assembly(
    agent_id: str | None = None,
    *,
    port: int = DEFAULT_PORT,
) -> None:
    """Ensure the local ``aasm`` sidecar is running, starting it if necessary.

    Lifecycle per F115 / AAASM-1205:

    1. Probe ``host:port`` via :func:`is_running`; return early if the sidecar
       is already up (idempotent re-init).
    2. Resolve the binary via :func:`find_aasm_binary`.
    3. Spawn the sidecar via :func:`start_runtime`.

    ``agent_id`` is accepted to keep the ticket-specified signature stable;
    actual register-and-connect is performed by the existing gateway-aware
    ``agent_assembly.init_assembly`` once the sidecar is reachable.

    Raises:
        RuntimeError: when no ``aasm`` binary is found on disk. The message
            contains copy-paste install commands for all supported channels.
    """
    del agent_id  # not consumed at the lifecycle layer; see docstring
    if is_running(port):
        return
    binary = find_aasm_binary()
    if binary is None:
        raise RuntimeError(INSTALL_HINT)
    start_runtime(binary, port=port)
