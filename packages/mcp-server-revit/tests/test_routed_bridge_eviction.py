"""Routed bridge clients: no network call under the lock, and dead Revits are evicted."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from revit_mcp_server.bridge import discovery
from revit_mcp_server.bridge.routing import RoutedBridgeCache
from revit_mcp_server.config import BridgeMode
from revit_mcp_server.errors import BridgeError, CommandFailed
from revit_mcp_server.providers.revit import RevitProvider
from revit_mcp_server.security.workspace import WorkspaceMonitor

A = ("http://127.0.0.1:4101", "tok-a")
B = ("http://127.0.0.1:4102", "tok-b")


class FakeBridge:
    def __init__(self, url, token=None, healthy=True, init_gate=None):
        self.url, self.token = url, token
        self.healthy = healthy
        self.init_gate = init_gate
        self.closed = False
        self.health_calls = 0

    def initialize(self):
        if self.init_gate is not None:
            self.init_gate.wait(5)

    def _get(self, path):
        assert path == "/health"
        self.health_calls += 1
        if not self.healthy:
            raise BridgeError("connection refused")
        return {"status": "healthy"}

    def close(self):
        self.closed = True


def _switch(key):
    return SimpleNamespace(provider_id="revit", endpoint=key[0], session_token=key[1])


@pytest.fixture
def registry(monkeypatch):
    live = {"keys": [A, B], "fail": False}

    def fake_list(registry_dir=None, *, prune=True):
        if live["fail"]:
            raise OSError("registry unreadable")
        return [_switch(k) for k in live["keys"]]

    monkeypatch.setattr(discovery, "discover_switch_list", fake_list)
    return live


def _provider(tmp_path, made):
    def factory(url, token=None):
        bridge = FakeBridge(url, token)
        made.append(bridge)
        return bridge

    return RevitProvider(
        workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.bridge,
        bridge_url="http://127.0.0.1:3000", bridge_factory=factory,
    )


def test_client_reused_while_its_revit_is_live(tmp_path, registry):
    made = []
    provider = _provider(tmp_path, made)
    with provider.routed_to(*A) as first:
        pass
    with provider.routed_to(*A) as second:
        pass
    assert first is second
    assert not first.closed


def test_client_evicted_when_registry_entry_is_gone(tmp_path, registry):
    made = []
    provider = _provider(tmp_path, made)
    with provider.routed_to(*A) as bridge_a:
        pass
    registry["keys"] = [B]  # Revit A closed and its registry file was removed
    with provider.routed_to(*B):
        pass
    assert bridge_a.closed
    assert A not in provider._routed_bridges
    assert B in provider._routed_bridges


def test_unreadable_registry_evicts_nothing(tmp_path, registry):
    made = []
    provider = _provider(tmp_path, made)
    with provider.routed_to(*A) as bridge_a:
        pass
    registry["fail"] = True
    with provider.routed_to(*B):
        pass
    assert not bridge_a.closed
    assert A in provider._routed_bridges


def test_client_evicted_after_repeated_failed_health_checks(tmp_path, registry):
    made = []
    provider = _provider(tmp_path, made)
    strikes = provider._routed_bridges.max_strikes
    for attempt in range(strikes):
        with pytest.raises(BridgeError):
            with provider.routed_to(*A) as bridge:
                bridge.healthy = False
                raise BridgeError("Bridge request failed after 3 attempts")
        if attempt < strikes - 1:
            assert A in provider._routed_bridges
    assert A not in provider._routed_bridges
    assert bridge.closed and bridge.health_calls == strikes
    with provider.routed_to(*A) as fresh:
        pass
    assert fresh is not bridge  # the next call builds a new client


def test_healthy_probe_or_success_resets_strikes(tmp_path, registry):
    made = []
    provider = _provider(tmp_path, made)
    with pytest.raises(BridgeError):
        with provider.routed_to(*A) as bridge:
            bridge.healthy = False
            raise BridgeError("timeout")
    assert provider._routed_bridges.strikes(A) == 1
    bridge.healthy = True
    with pytest.raises(BridgeError):
        with provider.routed_to(*A):
            raise BridgeError("one transient error")
    assert provider._routed_bridges.strikes(A) == 0


def test_command_failure_is_not_a_strike(tmp_path, registry):
    made = []
    provider = _provider(tmp_path, made)
    with pytest.raises(CommandFailed):
        with provider.routed_to(*A) as bridge:
            bridge.healthy = False
            raise CommandFailed("Revit refused the command")
    assert bridge.health_calls == 0
    assert provider._routed_bridges.strikes(A) == 0


def test_initialise_runs_outside_the_lock(tmp_path, registry):
    gate = threading.Event()
    entered = threading.Event()

    def factory(url, token=None):
        if url == A[0]:
            entered.set()
            return FakeBridge(url, token, init_gate=gate)
        return FakeBridge(url, token)

    provider = RevitProvider(
        workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.bridge,
        bridge_url="http://127.0.0.1:3000", bridge_factory=factory,
    )
    slow = threading.Thread(target=lambda: provider.routed_to(*A).__enter__())
    slow.start()
    try:
        assert entered.wait(5)
        done = threading.Event()

        def fast():
            with provider.routed_to(*B):
                done.set()

        worker = threading.Thread(target=fast)
        worker.start()
        assert done.wait(2), "a slow initialise for one Revit blocked routing to another"
        worker.join(2)
    finally:
        gate.set()
        slow.join(5)


def test_concurrent_build_keeps_one_client_and_closes_the_other():
    cache = RoutedBridgeCache()
    gate = threading.Event()
    built = []

    def factory(url, token=None):
        bridge = FakeBridge(url, token, init_gate=gate)
        built.append(bridge)
        return bridge

    results = []
    threads = [threading.Thread(target=lambda: results.append(cache.get(A, factory))) for _ in range(2)]
    for t in threads:
        t.start()
    while len(built) < 2:
        threading.Event().wait(0.01)
    gate.set()
    for t in threads:
        t.join(5)
    assert results[0] is results[1]
    assert sum(b.closed for b in built) == 1
    assert len(cache) == 1


def test_shutdown_closes_routed_clients(tmp_path, registry):
    import asyncio

    made = []
    provider = _provider(tmp_path, made)
    with provider.routed_to(*A) as bridge_a:
        pass
    asyncio.run(provider.shutdown())
    assert bridge_a.closed
    assert len(provider._routed_bridges) == 0
