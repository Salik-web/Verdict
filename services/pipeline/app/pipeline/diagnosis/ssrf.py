"""SSRF guard for the scraper.

Before ANY outbound fetch (and on every redirect hop) the target URL must pass
`assert_public_url`. We allow only http/https to hostnames that resolve
exclusively to globally-routable public IPs. Everything else — private ranges,
loopback, link-local (incl. the 169.254.169.254 cloud-metadata endpoint),
shared/CGNAT, reserved, multicast — is rejected.

Scraped content is untrusted DATA and is never passed to a model as instructions.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

# Hostnames that must never be fetched even if DNS would resolve them.
_BLOCKED_HOSTNAMES = {
    "metadata.google.internal",
    "metadata",
    "instance-data",
    "instance-data.ec2.internal",
}

# Explicit cloud-metadata IPs (also caught by the is_global check below, but
# listed for clarity and defense in depth).
_BLOCKED_IPS = {
    ipaddress.ip_address("169.254.169.254"),  # AWS/GCP/Azure IMDS
    ipaddress.ip_address("fd00:ec2::254"),  # AWS IMDSv2 (IPv6)
}


class SSRFError(ValueError):
    """Raised when a URL is not allowed to be fetched."""


def _ip_is_public(ip: ipaddress._BaseAddress) -> bool:
    if ip in _BLOCKED_IPS:
        return False
    # is_global is True only for public, routable addresses. It already excludes
    # private, loopback, link-local, reserved, multicast, unspecified, and the
    # 100.64/10 shared (CGNAT) range.
    return bool(ip.is_global)


def assert_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"scheme not allowed: {parsed.scheme or '(none)'}")

    host = parsed.hostname
    if not host:
        raise SSRFError("URL has no host")
    if host.lower() in _BLOCKED_HOSTNAMES:
        raise SSRFError(f"blocked hostname: {host}")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    # Resolve the host and require EVERY resolved address to be public. This
    # covers IP-literal hosts too (getaddrinfo returns the literal).
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SSRFError(f"cannot resolve host: {host}") from exc

    if not infos:
        raise SSRFError(f"host did not resolve: {host}")

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not _ip_is_public(ip):
            raise SSRFError(f"host {host} resolves to non-public address {ip}")
