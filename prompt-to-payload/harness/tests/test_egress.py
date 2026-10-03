"""Offline guard tests.

The guard has to refuse before a socket opens. One that blocks after connecting
has already told a defender you are there.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from payload import egress


def _locked(value: str):
    os.environ["PAYLOAD_OFFLINE"] = value


def test_locked_by_default():
    os.environ.pop("PAYLOAD_OFFLINE", None)
    assert egress.is_locked() is True
    print("  locked by default with no environment variable set")


def test_loopback_forms_are_permitted():
    _locked("1")
    for url in [
        "http://127.0.0.1:11434/v1/chat/completions",
        "http://localhost:8080/v1",
        "http://[::1]:11434/v1",
        "https://127.0.0.1/v1",
    ]:
        egress.check(url)  # must not raise
    print("  127.0.0.1, localhost and ::1 all permitted")


def test_external_hosts_are_refused_while_locked():
    _locked("1")
    refused = 0
    for url in [
        "https://api.openai.com/v1/chat/completions",
        "http://192.168.1.50:11434/v1",
        "http://8.8.8.8/",
        "https://example.com/",
    ]:
        try:
            egress.check(url)
            print(f"  NOT BLOCKED: {url}")
        except egress.EgressBlocked:
            refused += 1
    assert refused == 4, f"only {refused}/4 refused"
    print("  external, LAN and raw-IP destinations all refused while locked")


def test_unlocking_permits_external():
    _locked("0")
    egress.check("https://example.com/")  # must not raise
    _locked("1")
    print("  explicit unlock permits external, for provisioning only")


def test_unresolvable_host_is_refused_not_allowed():
    # air-gapped box resolves nothing, so fail closed
    _locked("1")
    try:
        egress.check("http://host-that-does-not-exist.invalid/v1")
        print("  NOT BLOCKED: unresolvable host was allowed")
        raise AssertionError("unresolvable host should be refused")
    except egress.EgressBlocked:
        print("  unresolvable host refused, not allowed through")


def test_missing_host_is_refused():
    _locked("1")
    try:
        egress.check("not-a-url")
        raise AssertionError("malformed URL should be refused")
    except egress.EgressBlocked:
        print("  malformed URL refused")


def test_no_dns_query_is_emitted_for_a_refused_host():
    """No DNS for a host we are about to refuse. A lookup is traffic too."""
    _locked("1")
    import socket as _socket

    called = []
    real = _socket.getaddrinfo

    def tripwire(*args, **kwargs):
        called.append(args[0])
        return real(*args, **kwargs)

    _socket.getaddrinfo = tripwire
    try:
        for url in ["https://api.openai.com/v1", "http://client-internal.example/",
                    "http://8.8.8.8/", "http://192.168.1.50:11434/v1"]:
            try:
                egress.check(url)
                raise AssertionError(f"{url} was not refused")
            except egress.EgressBlocked:
                pass
        assert not called, f"resolved hosts it was going to refuse: {called}"
        # loopback by name is still allowed, and comes from /etc/hosts
        egress.check("http://localhost:11434/v1")
    finally:
        _socket.getaddrinfo = real
    print("  no DNS emitted for refused hosts; localhost still permitted")


def test_model_client_refuses_before_opening_a_socket():
    # the guard belongs in front of the HTTP call, not inside it
    _locked("1")
    from payload.config import Config, RoleConfig
    from payload.models import ModelClient

    cfg = Config()
    cfg.roles["plan"] = RoleConfig(model="m",
                                   endpoint="https://api.openai.com/v1")
    client = ModelClient(cfg)
    try:
        client.chat("plan", [{"role": "user", "content": "hi"}], retries=0)
        raise AssertionError("client reached a remote endpoint while locked")
    except egress.EgressBlocked:
        print("  ModelClient refuses a remote endpoint before connecting")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"egress guard: {len(tests)} tests\n")
    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            print(f"  FAIL {test.__name__}: {exc}")
            failed += 1
    os.environ["PAYLOAD_OFFLINE"] = "1"
    print(f"\n{len(tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
