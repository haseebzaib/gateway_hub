"""Where a reader of a notification can reach this gateway's console.

A notification is read away from the site, so the address that matters most
is the one that works from anywhere: the Tailscale address. The local-network
address follows for someone on site. Both are detected at send time, because
DHCP and a re-joined tailnet both change them over the gateway's lifetime and
a hard-coded URL would quietly start pointing at nothing.

Detection uses the kernel directly (no subprocess, no extra package) and is
cached briefly so a burst of notifications does not repeat it.
"""

from __future__ import annotations

import fcntl
import ipaddress
import socket
import struct
import time
from urllib.parse import urlsplit


DEFAULT_PORT = 8000
CACHE_S = 60.0
_SIOCGIFADDR = 0x8915
# Tailscale hands out addresses from the CGNAT range.
_TAILNET = ipaddress.ip_network("100.64.0.0/10")

_cache: tuple[float, str, list[dict[str, str]]] | None = None


def console_links(configured_url: str = "") -> list[dict[str, str]]:
    """Ordered console base URLs: Tailscale, then local, then the configured one."""
    global _cache
    now = time.monotonic()
    if _cache is not None and _cache[1] == configured_url and now - _cache[0] < CACHE_S:
        return _cache[2]

    scheme, port = "http", DEFAULT_PORT
    configured_host = ""
    if configured_url:
        parts = urlsplit(configured_url)
        scheme = parts.scheme or scheme
        port = parts.port or port
        configured_host = parts.hostname or ""

    links: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(label: str, host: str | None) -> None:
        if host and host not in seen:
            seen.add(host)
            links.append({"label": label, "url": f"{scheme}://{host}:{port}"})

    add("Remote access (Tailscale)", _tailscale_ip())
    add("Local network", _primary_ip())
    if configured_host:
        add("Configured address", configured_host)

    _cache = (now, configured_url, links)
    return links


def _tailscale_ip() -> str | None:
    ip = _interface_ip("tailscale0")
    if ip:
        return ip
    # Some installs name the interface differently; fall back to any address
    # in the tailnet range.
    for _, name in _interfaces():
        ip = _interface_ip(name)
        if ip and ipaddress.ip_address(ip) in _TAILNET:
            return ip
    return None


def _primary_ip() -> str | None:
    """The source address of the default route — the one LAN clients use.

    Connecting a UDP socket sends nothing; it only asks the kernel which
    address it would use.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("1.1.1.1", 80))
            ip = sock.getsockname()[0]
    except OSError:
        ip = None
    if ip and not ip.startswith("127.") and ipaddress.ip_address(ip) not in _TAILNET:
        return ip
    # No default route (isolated site network): first non-loopback address.
    for _, name in _interfaces():
        if name == "lo" or name.startswith("tailscale"):
            continue
        ip = _interface_ip(name)
        if ip:
            return ip
    return None


def _interfaces() -> list[tuple[int, str]]:
    try:
        return socket.if_nameindex()
    except OSError:
        return []


def _interface_ip(name: str) -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            packed = fcntl.ioctl(
                sock.fileno(), _SIOCGIFADDR, struct.pack("256s", name[:15].encode())
            )
        return socket.inet_ntoa(packed[20:24])
    except OSError:
        return None


__all__ = ["console_links"]
