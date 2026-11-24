"""Cache of bridge clients for the panel hub's per-Revit routing.

The lock guards the dictionary only. Building a client, its network initialise, health probes
and close() all run outside the lock, so one slow or dead Revit does not stall calls routed to
another. A cached client is evicted when its Revit's registry entry is gone, or when its /health
probe fails ``max_strikes`` times in a row after failed calls.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, Iterable, Tuple

logger = logging.getLogger(__name__)

RouteKey = Tuple[str, Any]
DEFAULT_MAX_STRIKES = 3


def _close(bridge: Any) -> None:
    close = getattr(bridge, "close", None)
    if callable(close):
        try:
            close()
        except Exception as e:  # closing a dead client must not break routing
            logger.debug("Closing an evicted bridge client failed: %s", type(e).__name__)


def health_ok(bridge: Any) -> bool:
    """One /health probe. A client without a health call cannot be judged and counts as healthy."""
    probe = getattr(bridge, "_get", None)
    if not callable(probe):
        return True
    try:
        health = probe("/health")
    except Exception:
        return False
    return isinstance(health, dict) and health.get("status") == "healthy"


class RoutedBridgeCache:
    def __init__(self, max_strikes: int = DEFAULT_MAX_STRIKES) -> None:
        self.max_strikes = max(1, int(max_strikes))
        self._lock = threading.Lock()
        self._bridges: Dict[RouteKey, Any] = {}
        self._strikes: Dict[RouteKey, int] = {}

    def __contains__(self, key: RouteKey) -> bool:
        with self._lock:
            return key in self._bridges

    def __len__(self) -> int:
        with self._lock:
            return len(self._bridges)

    def values(self) -> list:
        with self._lock:
            return list(self._bridges.values())

    def strikes(self, key: RouteKey) -> int:
        with self._lock:
            return self._strikes.get(key, 0)

    def get(self, key: RouteKey, factory: Callable[[str, Any], Any]) -> Any:
        """The cached client for ``key``, or a new one built and initialised outside the lock."""
        with self._lock:
            bridge = self._bridges.get(key)
        if bridge is not None:
            return bridge
        endpoint, token = key
        bridge = factory(endpoint, token)
        initialised = True
        if hasattr(bridge, "initialize"):
            try:
                bridge.initialize()
            except Exception as e:
                initialised = False
                logger.error("Failed to initialize routed Revit bridge client: %s", type(e).__name__)
        with self._lock:
            existing = self._bridges.get(key)
            if existing is None:
                self._bridges[key] = bridge
                self._strikes[key] = 0 if initialised else 1
        if existing is not None:
            _close(bridge)  # another thread cached one first; keep that one
            return existing
        return bridge

    def record_success(self, key: RouteKey) -> None:
        with self._lock:
            if key in self._bridges:
                self._strikes[key] = 0

    def record_failure(self, key: RouteKey, bridge: Any) -> bool:
        """After a failed call: probe /health outside the lock. Returns True when the client was evicted."""
        if health_ok(bridge):
            self.record_success(key)
            return False
        with self._lock:
            if self._bridges.get(key) is not bridge:
                return False  # already evicted or replaced
            strikes = self._strikes.get(key, 0) + 1
            self._strikes[key] = strikes
            evict = strikes >= self.max_strikes
            if evict:
                del self._bridges[key]
                del self._strikes[key]
        if evict:
            logger.warning("Evicted the cached bridge client for %s after %d failed health checks.", key[0], strikes)
            _close(bridge)
        return evict

    def evict_missing(self, live: Iterable[RouteKey], keep: RouteKey | None = None) -> int:
        """Drop cached clients whose (endpoint, token) is no longer in the live registry."""
        live_keys = set(live)
        if keep is not None:
            live_keys.add(keep)
        with self._lock:
            gone = [k for k in self._bridges if k not in live_keys]
            removed = [(k, self._bridges.pop(k)) for k in gone]
            for k in gone:
                self._strikes.pop(k, None)
        for key, bridge in removed:
            logger.info("Evicted the cached bridge client for %s: its Revit registry entry is gone.", key[0])
            _close(bridge)
        return len(removed)

    def close_all(self) -> None:
        with self._lock:
            bridges = list(self._bridges.values())
            self._bridges.clear()
            self._strikes.clear()
        for bridge in bridges:
            _close(bridge)
