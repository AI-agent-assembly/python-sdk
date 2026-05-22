"""Resolve the gateway URL and API key for ``init_assembly``.

Implements the zero-config developer-experience contract from Epic 17 (S-G):
``init_assembly()`` with no arguments and no environment variables should
discover a local gateway at ``http://localhost:7391`` — probing it, and
auto-starting ``aasm start --mode local --foreground`` when not running.

Resolution precedence (highest first)::

    1. Explicit kwarg passed to init_assembly
    2. Environment variable (AAASM_GATEWAY_URL / AAASM_API_KEY)
    3. Config file (~/.aasm/config.yaml, optional dependency)
    4. Local default: probe http://localhost:7391, auto-start if absent
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from agent_assembly.exceptions import ConfigurationError, GatewayError

DEFAULT_GATEWAY_URL = "http://localhost:7391"
DEFAULT_HEALTHZ_PATH = "/healthz"
DEFAULT_PROBE_TIMEOUT_SECONDS = 0.5
DEFAULT_AUTO_START_TIMEOUT_SECONDS = 5.0
DEFAULT_CONFIG_FILE_PATH = "~/.aasm/config.yaml"

ENV_GATEWAY_URL = "AAASM_GATEWAY_URL"
ENV_API_KEY = "AAASM_API_KEY"

AASM_AUTO_START_ARGV = ("start", "--mode", "local", "--foreground")


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
    return 200 <= response.status_code < 300


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
        import yaml  # type: ignore[import-untyped]  # noqa: PLC0415 — soft dependency
    except ImportError:
        return {}

    resolved = Path(path).expanduser()
    if not resolved.is_file():
        return {}

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
            "Install it with: pip install agent-assembly[cli]"
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

    env_value = os.environ.get(ENV_GATEWAY_URL)
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
