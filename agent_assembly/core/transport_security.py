"""Shared transport-security validation for gateway connections (AAASM-3685/3725).

The SDK reaches the governance gateway over two transports that both carry
sensitive material:

* the op-control gRPC stream (``op_control.py``), which carries the agent
  identity triple and operator pause / terminate signals;
* the control-plane HTTP API (``client/gateway.py``), which sends the API key
  as an ``Authorization: Bearer`` header and also carries resolved credential
  values (``dispatch_tool``) and topology metadata (``report_edge``) — so the
  channel is sensitive even when no API key is set.

Neither must travel unencrypted to a **non-loopback** host without an explicit
opt-in. A loopback target is the local dev-mode gateway, where plaintext is the
documented default; anything else is presumed remote and must be encrypted.

This module centralises the loopback decision and the two enforcement helpers
so the gRPC and HTTP paths agree on what "secure" means (mirrors node-sdk
AAASM-3123).
"""

from __future__ import annotations

import warnings
from urllib.parse import urlsplit

__all__ = [
    "LOOPBACK_HOSTS",
    "gateway_host_of",
    "is_loopback_target",
    "require_secure_grpc_target",
    "require_secure_http_url",
    "warn_if_insecure_http_url",
]

# Hosts treated as loopback for the secure-by-default transport decision.
# A loopback gateway is the local dev-mode CP, where plaintext is the documented
# default; anything else is presumed remote and must be encrypted.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


def gateway_host_of(gateway_url: str) -> str:
    """Extract the bare host from a gateway target.

    Accepts a gRPC ``host:port`` target, a bare host, or a full URL with a
    scheme (``http://host:port/path``). IPv6 bracket form (``[::1]:7391``) is
    preserved with its brackets so it can be matched against
    :data:`LOOPBACK_HOSTS`. The result is lower-cased for case-insensitive
    comparison.
    """
    target = gateway_url.strip()

    # Full URL with a scheme — let urlsplit pull out the host:port authority.
    if "://" in target:
        target = urlsplit(target).netloc

    # Strip any userinfo (``user:pass@host``) — only the host matters here.
    if "@" in target:
        target = target.rsplit("@", 1)[1]

    # Bracketed IPv6 (``[::1]`` or ``[::1]:7391``): keep the brackets, drop the
    # trailing ``:port`` that sits *outside* the closing bracket.
    if target.startswith("["):
        closing = target.find("]")
        if closing != -1:
            return target[: closing + 1].lower()
        return target.lower()

    # Bare IPv6 without brackets (more than one colon) — no port to strip.
    if target.count(":") > 1:
        return target.lower()

    # host or host:port — drop the port.
    return target.rsplit(":", 1)[0].lower() if ":" in target else target.lower()


def is_loopback_target(gateway_url: str) -> bool:
    """Return True iff ``gateway_url`` points at a loopback host."""
    return gateway_host_of(gateway_url) in LOOPBACK_HOSTS


def require_secure_grpc_target(gateway_url: str, *, allow_insecure: bool) -> None:
    """Validate that a plaintext gRPC channel to ``gateway_url`` is permitted.

    A loopback target is always allowed (local dev gateway). A non-loopback
    target requires the caller to set ``allow_insecure`` — otherwise raise
    :class:`ValueError`, because the op-control stream carries the agent
    identity and operator control signals.
    """
    if is_loopback_target(gateway_url) or allow_insecure:
        return
    raise ValueError(
        f"Refusing to open an insecure (plaintext) gRPC channel to non-loopback "
        f"gateway {gateway_url!r}. Use a TLS channel via channel_factory, or pass "
        f"allow_insecure=True to explicitly opt in (loopback dev only)."
    )


def require_secure_http_url(gateway_url: str, *, has_api_key: bool, allow_insecure: bool) -> None:
    """Validate that an ``http://`` control-plane URL is permitted.

    The control-plane channel carries sensitive material even when no API key
    is set: ``dispatch_tool`` returns resolved credential values and
    ``report_edge`` posts topology metadata. A Bearer credential (when a key
    *is* set) is merely the most obvious secret. A plaintext ``http://`` URL to
    a non-loopback host would therefore leak whichever of these flow, so the
    guard refuses regardless of ``has_api_key``; ``has_api_key`` only sharpens
    the error message. Refuse unless the target is loopback or
    ``allow_insecure`` is set. ``https://`` URLs (and non-http schemes) always
    pass.
    """
    scheme = urlsplit(gateway_url.strip()).scheme.lower()
    if scheme != "http":
        return
    if is_loopback_target(gateway_url) or allow_insecure:
        return
    if has_api_key:
        raise ValueError(
            f"Refusing to send an Authorization: Bearer credential over a plaintext "
            f"(non-TLS) connection to non-loopback gateway {gateway_url!r}. Use an "
            f"https:// endpoint, or pass allow_insecure=True to explicitly opt in "
            f"(loopback dev only)."
        )
    raise ValueError(
        f"Refusing to open a plaintext (non-TLS) control-plane connection to "
        f"non-loopback gateway {gateway_url!r}. The control-plane channel carries "
        f"resolved credentials and topology metadata that would travel unencrypted "
        f"even without an API key. Use an https:// endpoint, or pass "
        f"allow_insecure=True to explicitly opt in (loopback dev only)."
    )


def warn_if_insecure_http_url(gateway_url: str, *, has_api_key: bool) -> None:
    """Emit a warning when a non-loopback ``http://`` gateway is used.

    Resolution-time advisory counterpart to :func:`require_secure_http_url`:
    the resolver knows the URL and whether a key is set before any request is
    issued, so it warns early. Because the control-plane channel carries
    resolved credentials and topology metadata even without an API key, the
    warning fires for any non-loopback plaintext ``http://`` target regardless
    of ``has_api_key`` — the key only sharpens the message. The hard refusal
    still happens later in ``GatewayClient`` (AAASM-3725). ``https://`` and
    loopback targets are silent.
    """
    scheme = urlsplit(gateway_url.strip()).scheme.lower()
    if scheme != "http" or is_loopback_target(gateway_url):
        return
    if has_api_key:
        warnings.warn(
            f"Gateway {gateway_url!r} uses plaintext http:// while an API key is set; "
            f"the Authorization: Bearer credential would travel unencrypted. Use "
            f"https:// for non-loopback gateways.",
            stacklevel=3,
        )
        return
    warnings.warn(
        f"Gateway {gateway_url!r} uses plaintext http:// to a non-loopback host; "
        f"control-plane payloads (resolved credentials, topology metadata) would "
        f"travel unencrypted. Use https:// for non-loopback gateways.",
        stacklevel=3,
    )
