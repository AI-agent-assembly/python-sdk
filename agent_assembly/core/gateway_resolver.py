"""Resolve the gateway URL and API key for ``init_assembly``.

Implements the zero-config developer-experience contract from Epic 17 (S-G):
``init_assembly()`` with no arguments and no environment variables should
discover a local gateway at ``http://localhost:7391`` — probing it, and
auto-starting ``aasm start --mode local --foreground`` when not running.

Resolution precedence (highest first)::

    1. Explicit kwarg passed to init_assembly
    2. Environment variable: ``AA_GATEWAY_URL`` / ``AA_API_KEY`` (canonical),
       falling back to the deprecated ``AAASM_GATEWAY_URL`` / ``AAASM_API_KEY``
       aliases (a ``DeprecationWarning`` is emitted when the legacy var is used)
    3. Config file (~/.aasm/config.yaml, optional dependency)
    4. Local default: probe http://localhost:7391, auto-start if absent
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import subprocess
import time
import warnings
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from agent_assembly.core.transport_security import require_secure_grpc_target
from agent_assembly.exceptions import ConfigurationError, GatewayError

logger = logging.getLogger(__name__)

DEFAULT_GATEWAY_URL = "http://localhost:7391"

# Agent registration is the SDK's one *direct* gateway gRPC call
# (``AgentLifecycleService.Register`` via ``aa-sdk-client``). It targets the
# gateway's gRPC port, which is distinct from the REST port the ``gateway_url``
# HTTP client uses — dialing the REST port for registration hits a socket with no
# ``AgentLifecycleService`` and fails (AAASM-4547).
DEFAULT_GRPC_PORT = 50051
DEFAULT_GRPC_ENDPOINT = "http://127.0.0.1:50051"
ENV_GATEWAY_ENDPOINT = "AA_GATEWAY_ENDPOINT"
DEFAULT_HEALTHZ_PATH = "/healthz"
DEFAULT_PROBE_TIMEOUT_SECONDS = 0.5
DEFAULT_AUTO_START_TIMEOUT_SECONDS = 5.0
DEFAULT_CONFIG_FILE_PATH = "~/.aasm/config.yaml"

ENV_GATEWAY_URL = "AA_GATEWAY_URL"
ENV_API_KEY = "AA_API_KEY"

# Deprecated aliases, kept for backwards compatibility. Reading one of these
# (when its canonical ``AA_*`` counterpart is unset) emits a DeprecationWarning.
LEGACY_ENV_GATEWAY_URL = "AAASM_GATEWAY_URL"
LEGACY_ENV_API_KEY = "AAASM_API_KEY"

AASM_AUTO_START_ARGV = ("start", "--mode", "local", "--foreground")

# Tracks which legacy env vars have already warned, so the DeprecationWarning
# fires once per variable rather than on every resolution call.
_warned_legacy_env: set[str] = set()


def _warn_if_world_readable(path: Path) -> None:
    """Emit a warning when ``path`` is readable by group or other.

    Defense-in-depth for ``~/.aasm/config.yaml``, which may contain an
    ``api_key``. Follows the AWS CLI / gcloud / docker convention of
    warning-not-refusing: the read still proceeds, but the operator is
    prompted to ``chmod 600``. Any stat failure (missing, unreadable) is
    swallowed — the caller has already checked existence and will handle
    the read error path itself.
    """
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return
    if mode & 0o077:
        logger.warning(
            "Config file %s has group/other-readable permissions (mode %o); run `chmod 600 %s` to secure it.",
            path,
            mode,
            path,
        )


def _resolve_env(canonical: str, legacy: str) -> str | None:
    """Read ``canonical`` first, falling back to the deprecated ``legacy`` var.

    Returns the resolved value, or ``None`` when neither is set. When the value
    comes from the ``legacy`` alias, a ``DeprecationWarning`` is emitted once
    per legacy variable directing the caller to the canonical ``AA_*`` name.
    """
    value = os.environ.get(canonical)
    if value:
        return value

    legacy_value = os.environ.get(legacy)
    if legacy_value:
        if legacy not in _warned_legacy_env:
            _warned_legacy_env.add(legacy)
            warnings.warn(
                f"Environment variable {legacy} is deprecated; use {canonical} instead.",
                DeprecationWarning,
                stacklevel=2,
            )
        return legacy_value

    return None


def _probe_healthz(base_url: str, timeout: float = DEFAULT_PROBE_TIMEOUT_SECONDS) -> bool:
    """Return True if a gateway responds 2xx at ``{base_url}/healthz``.

    A short timeout keeps the local-dev probe near-instant when nothing is
    listening; any network/HTTP error is swallowed and reported as False.
    """
    url = base_url.rstrip("/") + DEFAULT_HEALTHZ_PATH
    try:
        response = httpx.get(url, timeout=timeout)
    except httpx.HTTPError:
        return False
    status: int = response.status_code
    return 200 <= status < 300


def _wait_for_healthz(
    base_url: str,
    timeout: float = DEFAULT_AUTO_START_TIMEOUT_SECONDS,
    poll_interval: float = 0.1,
) -> bool:
    """Poll the gateway healthz endpoint until success or timeout.

    Returns True as soon as ``_probe_healthz`` succeeds. Returns False if
    the gateway is not ready within ``timeout`` seconds. The poll interval
    is short (default 100ms) so the auto-start path feels instant when the
    local CP comes up quickly.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _probe_healthz(base_url):
            return True
        time.sleep(poll_interval)
    return _probe_healthz(base_url)


def _load_config_file(path: str = DEFAULT_CONFIG_FILE_PATH) -> dict[str, Any]:
    """Load ``~/.aasm/config.yaml`` if present.

    Returns an empty dict when the file is missing, when PyYAML is not
    installed (it is a soft dependency for SDK consumers), or when the
    file's contents are not a mapping. This keeps the resolver chain
    purely advisory at step 3 — never raises.
    """
    try:
        import yaml  # type: ignore[import-untyped,unused-ignore]  # noqa: PLC0415 — soft dep
    except ImportError:
        return {}

    resolved = Path(path).expanduser()
    if not resolved.is_file():
        return {}

    _warn_if_world_readable(resolved)

    try:
        loaded = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _auto_start_gateway(
    base_url: str = DEFAULT_GATEWAY_URL,
    timeout: float = DEFAULT_AUTO_START_TIMEOUT_SECONDS,
) -> None:
    """Spawn ``aasm start --mode local --foreground`` and wait until ready.

    Raises ``ConfigurationError`` if the ``aasm`` binary is not on the
    caller's PATH — the SDK cannot meaningfully auto-start without it.
    Raises ``GatewayError`` if the spawned gateway does not respond to
    ``/healthz`` within ``timeout`` seconds.

    The subprocess is detached via ``start_new_session=True`` so it
    survives the parent Python process — matching the ``docker``-style
    daemon hand-off described in Epic 17 S-G.
    """
    aasm_path = shutil.which("aasm")
    if aasm_path is None:
        raise ConfigurationError(
            f"No gateway found at {base_url} and 'aasm' is not on PATH. "
            "Install it with: pip install --pre 'agent-assembly[runtime]'"
        )

    subprocess.Popen(
        [aasm_path, *AASM_AUTO_START_ARGV],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    if not _wait_for_healthz(base_url, timeout=timeout):
        raise GatewayError(f"Auto-started gateway at {base_url} did not become ready within {timeout:g} seconds")


def resolve_gateway_url(explicit: str | None = None) -> str:
    """Resolve the gateway URL using the 4-step precedence chain.

    Returns the resolved URL. May spawn a local ``aasm`` subprocess
    (step 4 only). Raises ``ConfigurationError`` / ``GatewayError`` from
    ``_auto_start_gateway`` when the local default is needed but cannot
    be brought up.
    """
    if explicit:
        return explicit

    env_value = _resolve_env(ENV_GATEWAY_URL, LEGACY_ENV_GATEWAY_URL)
    if env_value:
        return env_value

    config = _load_config_file()
    agent_section = config.get("agent")
    if isinstance(agent_section, dict):
        config_url = agent_section.get("gateway_url")
        if isinstance(config_url, str) and config_url:
            return config_url

    if _probe_healthz(DEFAULT_GATEWAY_URL):
        return DEFAULT_GATEWAY_URL

    _auto_start_gateway(DEFAULT_GATEWAY_URL)
    return DEFAULT_GATEWAY_URL


def resolve_gateway_grpc_endpoint(gateway_url: str | None = None, *, allow_insecure: bool = False) -> str:
    """Resolve the gRPC endpoint the native ``register`` call should dial.

    Agent registration goes over the gateway's **gRPC** port (:50051), which is a
    different port from the **REST** ``gateway_url`` (:7391) the HTTP client uses.
    Passing the REST URL into ``register`` would dial a port that exposes no
    ``AgentLifecycleService`` and fail, so the register endpoint is resolved
    separately here (AAASM-4547).

    Resolution precedence (highest first):

        1. ``AA_GATEWAY_ENDPOINT`` — explicit operator override, honoured verbatim
           (the same env var the native ``aa-sdk-client`` resolver reads, so a
           value set for one path applies to both). As an explicit operator
           escape hatch — the ``channel_factory`` analogue of the op-control path
           (``op_control.py``) — it bypasses the TLS guard below; the operator has
           taken responsibility for the transport they named.
        2. The resolved REST ``gateway_url``'s host with the gRPC port (:50051)
           substituted — so a non-loopback gateway host registers against *that*
           host's gRPC port rather than always ``127.0.0.1``.
        3. The loopback default ``http://127.0.0.1:50051``.

    A **derived** (branch 2) plaintext ``http://`` endpoint to a non-loopback host
    is refused, mirroring the op-control stream's non-loopback→TLS contract
    (``require_secure_grpc_target``, AAASM-3685): the ``Register`` call carries the
    agent identity, so it must not travel unencrypted to a remote host by default.
    ``https://`` (TLS) and loopback targets always pass; pass ``allow_insecure`` to
    opt into plaintext to a non-loopback host (loopback dev / trusted-network only),
    exactly as op-control's ``connect`` does (AAASM-4655).

    :param gateway_url: The already-resolved REST gateway URL, used only for its
        host. When it carries no usable host the loopback default is returned.
    :param allow_insecure: Opt into a plaintext (non-TLS) register channel to a
        non-loopback host. Defaults to ``False`` (fail-closed).
    :returns: A gRPC endpoint URL (e.g. ``http://127.0.0.1:50051``).
    :raises ValueError: When the derived endpoint is plaintext ``http://`` to a
        non-loopback host and ``allow_insecure`` is not set.
    """
    env_value = os.environ.get(ENV_GATEWAY_ENDPOINT)
    if env_value:
        return env_value

    if gateway_url:
        parsed = urlparse(gateway_url)
        if parsed.hostname:
            scheme = parsed.scheme or "http"
            endpoint = f"{scheme}://{parsed.hostname}:{DEFAULT_GRPC_PORT}"
            # Only plaintext http:// needs the guard; https:// carries its own TLS
            # and loopback is the documented dev default (both pass through
            # require_secure_grpc_target unconditionally).
            if scheme == "http":
                require_secure_grpc_target(endpoint, allow_insecure=allow_insecure)
            return endpoint

    return DEFAULT_GRPC_ENDPOINT


def resolve_api_key(explicit: str | None = None) -> str:
    """Resolve the API key using the same 4-step precedence as the URL.

    Returns the resolved key (possibly empty for local mode, which
    accepts unauthenticated agents). Never raises — an empty API key
    is the documented "local dev" default per Epic 17.
    """
    if explicit:
        return explicit

    env_value = _resolve_env(ENV_API_KEY, LEGACY_ENV_API_KEY)
    if env_value:
        return env_value

    config = _load_config_file()
    agent_section = config.get("agent")
    if isinstance(agent_section, dict):
        config_key = agent_section.get("api_key")
        if isinstance(config_key, str) and config_key:
            return config_key

    return ""
