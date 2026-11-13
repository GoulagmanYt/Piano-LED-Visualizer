#!/usr/bin/env python3

import asyncio
import sys
from types import SimpleNamespace

import pytest

sys.path.append("./")
sys.path.append("../")

from webinterface import reject_foreign_origin, websocket_origin_allowed


@pytest.fixture(autouse=True)
def _guard_enabled(monkeypatch):
    monkeypatch.delenv("PLV_ALLOW_CROSS_SITE", raising=False)


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "pi.local:8765", "Origin": "http://pi.local"},
        {"Host": "192.168.4.1:8765", "Origin": "http://192.168.4.1:8080"},
        {"Host": "[fe80::1]:8765", "Origin": "http://[fe80::1]"},
        {"Host": "PI.local:8765", "Origin": "http://pi.LOCAL"},
        {"Host": "pi.local:8765"},
        {},
    ],
    ids=["mdns", "ip-other-port", "ipv6", "case-insensitive", "no-origin", "bare-script"],
)
def test_same_host_and_non_browser_clients_are_allowed(headers):
    assert websocket_origin_allowed(headers) is True


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "pi.local:8765", "Origin": "http://evil.example"},
        {"Host": "pi.local:8765", "Origin": "https://pi.local.evil.example"},
        {"Host": "pi.local:8765", "Origin": "null"},
        {"Host": "192.168.4.1:8765", "Origin": "http://192.168.4.2"},
        {"Origin": "http://evil.example"},
    ],
    ids=["other-site", "lookalike-suffix", "null", "other-ip", "missing-host"],
)
def test_pages_from_other_sites_are_refused(headers):
    assert websocket_origin_allowed(headers) is False


def test_the_check_can_be_disabled_for_reverse_proxies(monkeypatch):
    monkeypatch.setenv("PLV_ALLOW_CROSS_SITE", "1")

    assert websocket_origin_allowed({"Host": "pi.local", "Origin": "http://evil.example"}) is True


class _Socket:
    def __init__(self, headers, new_api=True):
        if new_api:
            self.request = SimpleNamespace(headers=headers, path="/learning")
        else:
            self.request_headers = headers
        self.closed_with = None

    async def close(self, code=1000, reason=""):
        self.closed_with = (code, reason)


def test_foreign_origin_connection_is_closed_with_policy_violation():
    socket = _Socket({"Host": "pi.local:8765", "Origin": "http://evil.example"})

    assert asyncio.run(reject_foreign_origin(socket)) is True
    assert socket.closed_with == (1008, "origin not allowed")


def test_legacy_websockets_api_is_checked_too():
    socket = _Socket({"Host": "pi.local:8765", "Origin": "http://evil.example"}, new_api=False)

    assert asyncio.run(reject_foreign_origin(socket)) is True
    assert socket.closed_with[0] == 1008


def test_legitimate_connection_is_left_open():
    socket = _Socket({"Host": "pi.local:8765", "Origin": "http://pi.local"})

    assert asyncio.run(reject_foreign_origin(socket)) is False
    assert socket.closed_with is None


def test_unknown_socket_objects_are_not_rejected():
    assert asyncio.run(reject_foreign_origin(SimpleNamespace())) is False
