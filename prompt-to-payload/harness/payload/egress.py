"""Offline guard.

Locked by default: a model or tool endpoint has to be loopback or the call is
refused before any socket opens. Unlocking is explicit and is meant for
provisioning only.

scripts/egress-test.sh exists for anyone who would rather not take this
module's word for it.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse


class EgressBlocked(RuntimeError):
    """Raised when a non-loopback destination is attempted while locked."""


def is_locked() -> bool:
    """True when the harness refuses non-loopback destinations.

    Locked by default. Provisioning sets PAYLOAD_OFFLINE=0 explicitly and
    temporarily; the run phase should never need to.
    """
    return os.environ.get("PAYLOAD_OFFLINE", "1") != "0"


def _resolves_to_loopback(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # Unresolvable. On an air-gapped host that is the expected state for
        # anything external, so treat it as not-loopback and refuse.
        return False

    addrs = {info[4][0] for info in infos}
    if not addrs:
        return False
    return all(ipaddress.ip_address(a).is_loopback for a in addrs)


def check(url: str) -> None:
    """Refuse `url` unless it is loopback, or the harness is unlocked.

    Raises EgressBlocked. Call this before opening any connection.

    Deliberately decides without resolving anything it does not have to. A DNS
    query is itself traffic leaving the machine, and on a segmented network a
    lookup for a client's hostname is exactly the kind of packet this harness
    exists to avoid emitting. So: IP literals are judged arithmetically, the
    well-known local names resolve (they come from /etc/hosts, not the
    network), and every other name is refused unresolved.
    """
    if not is_locked():
        return

    host = urlparse(url).hostname
    if host is None:
        raise EgressBlocked(f"cannot determine host from {url!r}")

    # An address literal needs no lookup at all.
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if address.is_loopback:
            return
        raise EgressBlocked(
            f"refusing to contact {host!r}: not a loopback address and the "
            f"harness is locked offline. Set PAYLOAD_OFFLINE=0 only during "
            f"provisioning."
        )

    # Names that come from /etc/hosts, not a nameserver.
    if host == "localhost" or host.endswith(".localhost"):
        if _resolves_to_loopback(host):
            return
        raise EgressBlocked(
            f"{host!r} did not resolve to loopback, which is unexpected. "
            f"Check /etc/hosts."
        )

    raise EgressBlocked(
        f"refusing to resolve {host!r}: the harness is locked offline, and a "
        f"DNS query is itself traffic leaving this machine. Use a loopback "
        f"address, or set PAYLOAD_OFFLINE=0 only during provisioning."
    )
