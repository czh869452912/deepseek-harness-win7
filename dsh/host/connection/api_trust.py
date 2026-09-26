"""
Browser-trust fence for every /api request.

1:1 port of `reference/packages/client/connection/src/api-request-trust.ts` plus
`loopback-hostname.ts`. Defends the two confused-deputy paths a browser opens
against a local HTTP API — DNS rebinding (Host names the attacker's domain while
the socket reaches this server) and cross-site requests fired from a malicious
page. The Host fence binds every request, browser-looking or not.
"""

import ipaddress
import json
import re
from typing import Any, List, Optional, Tuple

from dsh.host.connection.browser_auth import header, parse_host, whatwg_host

_DOMAIN_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?$")
_IPV4_LIKE = re.compile(r"^[0-9A-Fa-fxX.]+$")


def is_loopback_hostname(hostname: str) -> bool:
    """Whether a normalized URL hostname names the local loopback authority."""
    if hostname == "localhost" or hostname in ("::1", "[::1]"):
        return True
    parts = hostname.split(".")
    if len(parts) != 4 or parts[0] != "127":
        return False
    for part in parts:
        if not part.isdigit() or len(part) > 3 or int(part) > 255:
            return False
    return True


def _entry_parts(entry: str) -> Optional[Tuple[str, Optional[int]]]:
    return parse_host(entry)


def assert_trusted_authority(entry: Any) -> None:
    """
    Assert one configured `trustedHosts` entry is a bare authority (`host` or
    `host:port`) in canonical form: it must survive parsing unchanged (case
    aside). Anything parsing would silently rewrite is refused as a typo that
    must fail the load loudly.

    Python's URL parser is laxer than WHATWG's, so the canonical rendering is
    computed explicitly: whitespace/control characters, path/query/fragment/
    userinfo shapes, non-canonical IPv6 and IPv4 spellings, and zero-padded
    ports all fail here rather than silently authorizing a hostname prefix.
    """
    rejected = ValueError(
        f"client-connection: trustedHosts entry {json.dumps(entry)} is not a bare host[:port] authority"
    )
    if not isinstance(entry, str):
        raise rejected
    canonical = _canonical_authority_entry(entry)
    if canonical is None or canonical != entry.lower():
        raise rejected


def _canonical_authority_entry(entry: str) -> Optional[str]:
    """Canonical `host[:port]` rendering of one bare authority, or None."""
    if entry == "":
        return None
    if any(ord(char) <= 32 or ord(char) == 127 for char in entry):
        return None
    host, port = entry, None
    if entry.startswith("["):
        end = entry.find("]")
        if end == -1:
            return None
        rest = entry[end + 1:]
        if rest:
            if not rest.startswith(":"):
                return None
            port = rest[1:]
        try:
            hostname = "[%s]" % ipaddress.IPv6Address(entry[1:end]).compressed
        except ValueError:
            return None
    else:
        if ":" in entry:
            host, port = entry.rsplit(":", 1)
            if ":" in host:
                return None
        if host == "":
            return None
        if "." in host and _IPV4_LIKE.match(host) and any(char.isdigit() for char in host):
            parts = host.split(".")
            if len(parts) != 4:
                return None
            for part in parts:
                if not part.isdigit() or int(part) > 255 or (len(part) > 1 and part[0] == "0"):
                    return None
            hostname = ".".join(str(int(part)) for part in parts)
        else:
            if not all(_DOMAIN_LABEL.match(label) for label in host.split(".")):
                return None
            hostname = host.lower()
    if port is None:
        return hostname
    if not port.isdigit() or str(int(port)) != port or int(port) > 65535:
        return None
    return "%s:%s" % (hostname, port)


def _is_trusted_authority(hostname: str, port: Optional[int], trusted_hosts: List[str]) -> bool:
    """
    An entry with an explicit port matches that exact authority; a port-less
    entry matches the hostname on any port.
    """
    for entry in trusted_hosts:
        if not isinstance(entry, str):
            continue
        parts = _entry_parts(entry)
        if parts is None:
            continue
        entry_hostname, entry_port = parts
        if entry_port is None:
            if entry_hostname == hostname:
                return True
            continue
        if whatwg_host(entry) == whatwg_host(hostname if port is None else f"{hostname}:{port}"):
            return True
    return False


def is_trusted_api_request(request: Any, trusted_hosts: List[str]) -> bool:
    """
    Decide whether one /api request may reach the RPC bridge.

    True when the Host is ours (loopback or trusted) and any attached browser
    markers are same-origin.
    """
    headers = request.get("headers") if isinstance(request, dict) else None
    # Host fence (DNS-rebinding defense), applied to every request.
    host = header(headers, "host")
    if host is None:
        return False
    parts = parse_host(host)
    if parts is None:
        return False
    hostname, port = parts
    if not is_loopback_hostname(hostname) and not _is_trusted_authority(hostname, port, trusted_hosts):
        return False
    # Cross-site fence: an explicit cross-site marker is refused regardless of Origin.
    if header(headers, "sec-fetch-site") == "cross-site":
        return False
    # Origin fence: when a browser attaches an Origin it must be exactly this
    # authority. Absent Origin is fine — the Host fence above already bound the
    # request. The literal "null" is an opaque origin, refused.
    origin = header(headers, "origin")
    if origin is None:
        return True
    origin_host = whatwg_host(origin)
    if origin_host is None:
        return False
    return origin_host == whatwg_host(host)
