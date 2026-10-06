from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

# Hostnames / literals that must never be used as outbound fetch targets.
_BLOCKED_HOSTS = frozenset(
    {
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "kubernetes.default",
        "kubernetes.default.svc",
    }
)
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]", "::1"})


def _host_ip(hostname: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        return None


def validate_outbound_url(
    value: str,
    *,
    purpose: str,
    allow_http_loopback: bool = True,
    allow_private_http: bool = False,
) -> str:
    """Validate a user/org-supplied URL before Pigeon fetches it or passes it to LiteLLM.

    - Only http/https
    - No embedded credentials
    - No cloud-metadata / well-known internal hostnames
    - http only for loopback (and optionally private nets) when allowed
    """
    raw = value.strip()
    if not raw or "\x00" in raw:
        raise ValueError(f"{purpose} must be a non-empty URL")
    if len(raw) > 2000:
        raise ValueError(f"{purpose} is too long")

    try:
        parsed = urlparse(raw)
    except ValueError as exc:
        raise ValueError(f"{purpose} is not a valid URL") from exc

    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"{purpose} must use http or https")
    if not parsed.hostname:
        raise ValueError(f"{purpose} must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{purpose} must not contain credentials")

    host = parsed.hostname.lower()
    if host in _BLOCKED_HOSTS or host.endswith(".internal"):
        raise ValueError(f"{purpose} host is not allowed")

    ip = _host_ip(host)
    if ip is not None:
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            raise ValueError(f"{purpose} host is not allowed")
        if parsed.scheme == "http":
            if ip.is_loopback and allow_http_loopback:
                return raw
            if allow_private_http and (ip.is_private or ip.is_loopback):
                return raw
            raise ValueError(f"{purpose} must use https (http is only allowed for loopback)")
        if ip.is_loopback or ip.is_private or ip.is_link_local:
            # https to private/loopback is OK for self-hosted inference endpoints.
            return raw
        return raw

    if host in _LOOPBACK_HOSTS:
        if parsed.scheme == "http" and not allow_http_loopback:
            raise ValueError(f"{purpose} must use https")
        return raw

    if parsed.scheme == "http":
        raise ValueError(f"{purpose} must use https (http is only allowed for loopback)")
    return raw


def validate_inference_endpoint(value: str) -> str:
    """Endpoint used as LiteLLM api_base or classifier POST URL."""
    return validate_outbound_url(
        value, purpose="endpoint", allow_http_loopback=True, allow_private_http=False
    )


def validate_media_url(value: str) -> str:
    """Caller-supplied media URL that Pigeon may GET server-side."""
    return validate_outbound_url(
        value, purpose="mediaUrl", allow_http_loopback=True, allow_private_http=False
    )
