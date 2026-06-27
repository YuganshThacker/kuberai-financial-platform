"""
SSRF guard for outbound fetches of untrusted URLs.

Company PDF links and IR-page URLs are extracted from filing text / scraped HTML,
so an attacker who plants a URL in an NSE filing could otherwise make the crawler
hit internal or cloud-metadata endpoints (169.254.169.254, link-local, private
ranges) — a classic SSRF that, in CI/AWS, can leak role credentials.

Use is_public_url() to validate any untrusted URL, and safe_get() to fetch one
with per-redirect re-validation (auto-redirects disabled).
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

_BLOCKED_HOSTNAMES = {"metadata.google.internal", "metadata.goog"}
_ALLOWED_SCHEMES = ("http", "https")


def _ip_is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_reserved or addr.is_multicast or addr.is_unspecified
    )


def is_public_url(url: str) -> bool:
    """True only if scheme is http(s) and EVERY resolved address is public."""
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in _ALLOWED_SCHEMES or not p.hostname:
        return False
    if p.hostname.lower() in _BLOCKED_HOSTNAMES:
        return False
    port = p.port or (443 if p.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(p.hostname, port, proto=socket.IPPROTO_TCP)
    except Exception:
        return False
    if not infos:
        return False
    return all(_ip_is_public(info[4][0]) for info in infos)


def safe_get(url: str, *, headers: dict | None = None, timeout: float = 30.0,
             max_redirects: int = 5) -> httpx.Response:
    """GET with SSRF protection: validates the host and every redirect hop.

    Raises ValueError if the URL (or any redirect target) is non-public.
    """
    if not is_public_url(url):
        raise ValueError(f"blocked non-public URL: {url}")
    with httpx.Client(follow_redirects=False, timeout=timeout) as client:
        current = url
        for _ in range(max_redirects + 1):
            r = client.get(current, headers=headers or {})
            if r.is_redirect:
                loc = r.headers.get("location", "")
                current = str(httpx.URL(r.url).join(loc))
                if not is_public_url(current):
                    raise ValueError(f"blocked redirect to non-public URL: {current}")
                continue
            return r
    raise ValueError(f"too many redirects for {url}")
