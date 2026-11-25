"""Per-tool timeouts and rate limits for tool calls.

Timeouts apply to direct MCP tool calls (not run_async jobs or MCP tasks, which are meant
to run long). A read that runs out of time is cancelled and refused with kind
``tool_timeout``. A write is never cancelled and never booked as failed: it may still be
running in Revit, so its approved action stays used and is recorded as in flight (see
security/dispatch.py), exactly like a call that came back ``running``.

Rate limits are token buckets: one per client session (all tools), one per tool, and one
per panel hub route. A refused call did not run and did not use an approved action; the
refusal (kind ``rate_limited``) says how many seconds to wait. Approval tools are
human-only and never counted.

Configuration (environment, read once when the server starts):

- ``MCP_REVIT_TOOL_TIMEOUT``: default seconds per call (300). 0 turns the default off.
- ``MCP_REVIT_TOOL_TIMEOUTS``: JSON object, tool name to seconds, for example
  ``{"revit_export_ifc": 1800}``. 0 means no timeout for that tool.
- ``MCP_REVIT_RATE_LIMITS``: ``off``, or a JSON object whose keys ``session``,
  ``write_tool``, ``read_tool``, ``panel_execute`` and ``panel_chat`` take
  ``{"per_minute": N, "burst": M}``, and ``tools`` maps a tool name to the same shape.
  ``per_minute`` 0 turns that bucket off. Missing keys keep their defaults.

Invalid values are logged and replaced by the default; they never turn a limit off.
"""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional

logger = logging.getLogger(__name__)

TIMEOUT_ENV = "MCP_REVIT_TOOL_TIMEOUT"
TIMEOUTS_ENV = "MCP_REVIT_TOOL_TIMEOUTS"
RATE_LIMITS_ENV = "MCP_REVIT_RATE_LIMITS"

DEFAULT_TIMEOUT_SECONDS = 300.0
MAX_SESSIONS = 1024


@dataclass(frozen=True)
class Rate:
    """``per_minute`` tokens are added per minute, up to ``burst``. per_minute 0 means no limit."""
    per_minute: float
    burst: float

    @property
    def enabled(self) -> bool:
        return self.per_minute > 0


DEFAULT_RATES: Dict[str, Rate] = {
    "session": Rate(600, 300),
    "write_tool": Rate(120, 60),
    "read_tool": Rate(300, 150),
    "panel_execute": Rate(600, 300),
    "panel_chat": Rate(30, 10),
}


# -- configuration ---------------------------------------------------------------------

def _seconds(value: Any) -> Optional[float]:
    """A finite number of seconds >= 0, or None when the value is not one."""
    if isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip()) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _json_object(raw: str, name: str) -> Dict[str, Any]:
    try:
        value = json.loads(raw)
    except ValueError:
        value = None
    if not isinstance(value, dict):
        logger.warning("%s is not a JSON object; using the defaults.", name)
        return {}
    return value


@dataclass(frozen=True)
class Timeouts:
    default: float = DEFAULT_TIMEOUT_SECONDS
    overrides: Mapping[str, float] = None  # type: ignore[assignment]

    def for_tool(self, name: str) -> Optional[float]:
        """Seconds for this tool, or None when it has no timeout."""
        overrides = self.overrides or {}
        seconds = overrides.get(name, self.default)
        return seconds if seconds and seconds > 0 else None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Timeouts":
        env = os.environ if env is None else env
        default = DEFAULT_TIMEOUT_SECONDS
        raw = env.get(TIMEOUT_ENV)
        if raw is not None and raw.strip():
            parsed = _seconds(raw)
            if parsed is None:
                logger.warning("Invalid %s %r; using %d seconds. Use 0 to turn it off.",
                               TIMEOUT_ENV, raw, DEFAULT_TIMEOUT_SECONDS)
            else:
                default = parsed
        overrides: Dict[str, float] = {}
        raw = env.get(TIMEOUTS_ENV)
        if raw is not None and raw.strip():
            for tool, value in _json_object(raw, TIMEOUTS_ENV).items():
                parsed = _seconds(value)
                if parsed is None:
                    logger.warning("Invalid timeout %r for %s in %s; using the default.", value, tool, TIMEOUTS_ENV)
                    continue
                overrides[str(tool)] = parsed
        return cls(default, overrides)


def _rate(value: Any, fallback: Rate, label: str) -> Rate:
    if not isinstance(value, dict):
        logger.warning("Invalid rate limit %r for %s in %s; using the default.", value, label, RATE_LIMITS_ENV)
        return fallback
    per_minute = _seconds(value.get("per_minute", fallback.per_minute))
    burst = _seconds(value.get("burst", fallback.burst if per_minute is None else max(per_minute / 4, 1)))
    if per_minute is None or burst is None or (per_minute > 0 and burst < 1):
        logger.warning("Invalid rate limit %r for %s in %s; using the default.", value, label, RATE_LIMITS_ENV)
        return fallback
    return Rate(per_minute, burst)


@dataclass(frozen=True)
class RateConfig:
    rates: Mapping[str, Rate]
    tools: Mapping[str, Rate]
    enabled: bool = True

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "RateConfig":
        env = os.environ if env is None else env
        raw = (env.get(RATE_LIMITS_ENV) or "").strip()
        rates = dict(DEFAULT_RATES)
        tools: Dict[str, Rate] = {}
        if raw.lower() == "off":
            return cls(rates, tools, enabled=False)
        if raw:
            data = _json_object(raw, RATE_LIMITS_ENV)
            for key, value in data.items():
                if key == "tools":
                    if not isinstance(value, dict):
                        logger.warning("'tools' in %s must be a JSON object; ignored.", RATE_LIMITS_ENV)
                        continue
                    for tool, tool_value in value.items():
                        fallback = Rate(-1, -1)
                        rate = _rate(tool_value, fallback, f"tool {tool}")
                        if rate is not fallback:
                            tools[str(tool)] = rate
                elif key in rates:
                    rates[key] = _rate(value, rates[key], key)
                else:
                    logger.warning("Unknown key %r in %s; ignored.", key, RATE_LIMITS_ENV)
        return cls(rates, tools)


# -- token buckets ---------------------------------------------------------------------

class TokenBucket:
    def __init__(self, rate: Rate, clock: Callable[[], float]) -> None:
        self.rate = rate
        self._clock = clock
        self._tokens = float(rate.burst)
        self._stamp = clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._stamp)
        self._stamp = now
        self._tokens = min(float(self.rate.burst), self._tokens + elapsed * self.rate.per_minute / 60.0)

    def wait_seconds(self) -> float:
        """0 when a token is available now, otherwise the seconds until one is."""
        self._refill()
        if self._tokens >= 1:
            return 0.0
        return (1 - self._tokens) * 60.0 / self.rate.per_minute

    def take(self) -> None:
        self._tokens -= 1


@dataclass(frozen=True)
class Refusal:
    scope: str
    rate: Rate
    retry_after: float

    @property
    def retry_after_seconds(self) -> int:
        return max(1, math.ceil(self.retry_after))

    def message(self) -> str:
        return (
            f"Too many calls: {self.scope} allows {self.rate.per_minute:g} calls per minute "
            f"(burst {self.rate.burst:g}). Nothing ran and no approved action was used. "
            f"Try again in {self.retry_after_seconds} s."
        )


class RateLimiter:
    """Thread-safe token buckets. ``check`` takes one token from every bucket a call needs,
    or none at all when any of them is empty."""

    def __init__(self, config: RateConfig | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        self.config = config if config is not None else RateConfig.from_env()
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: Dict[str, TokenBucket] = {}
        self._sessions: "collections.OrderedDict[str, TokenBucket]" = collections.OrderedDict()

    def _bucket(self, key: str, rate: Rate) -> TokenBucket:
        bucket = self._buckets.get(key)
        if bucket is None or bucket.rate != rate:
            bucket = self._buckets[key] = TokenBucket(rate, self._clock)
        return bucket

    def _session_bucket(self, session: str, rate: Rate) -> TokenBucket:
        bucket = self._sessions.get(session)
        if bucket is None:
            bucket = TokenBucket(rate, self._clock)
            self._sessions[session] = bucket
            while len(self._sessions) > MAX_SESSIONS:
                self._sessions.popitem(last=False)
        else:
            self._sessions.move_to_end(session)
        return bucket

    def _take_all(self, needed: list) -> Optional[Refusal]:
        worst: Optional[Refusal] = None
        for scope, bucket in needed:
            wait = bucket.wait_seconds()
            if wait > 0 and (worst is None or wait > worst.retry_after):
                worst = Refusal(scope, bucket.rate, wait)
        if worst is None:
            for _scope, bucket in needed:
                bucket.take()
        return worst

    def check_tool(self, session: str, tool: str, writes: bool) -> Optional[Refusal]:
        """None when the call may run (tokens taken), else the refusal (nothing taken)."""
        if not self.config.enabled:
            return None
        rates = self.config.rates
        needed = []
        with self._lock:
            session_rate = rates["session"]
            if session_rate.enabled:
                needed.append(("this client session", self._session_bucket(session, session_rate)))
            tool_rate = self.config.tools.get(tool) or rates["write_tool" if writes else "read_tool"]
            if tool_rate.enabled:
                needed.append((f"tool '{tool}'", self._bucket("tool:" + tool, tool_rate)))
            return self._take_all(needed)

    def check_route(self, route: str) -> Optional[Refusal]:
        """Per-route bucket for the panel hub (``panel_execute`` or ``panel_chat``)."""
        if not self.config.enabled:
            return None
        rate = self.config.rates[route]
        if not rate.enabled:
            return None
        with self._lock:
            return self._take_all([(f"the panel hub route '{route}'", self._bucket("route:" + route, rate))])


# -- timeouts --------------------------------------------------------------------------

class ToolTimedOut(Exception):
    """The call outlived its timeout. ``task`` is still running for a write (never cancelled)."""

    def __init__(self, seconds: float, task: "asyncio.Future[Any]", kept_running: bool) -> None:
        super().__init__(f"The call did not finish within {seconds:g} s.")
        self.seconds = seconds
        self.task = task
        self.kept_running = kept_running


def _retrieve(task: "asyncio.Future[Any]") -> None:
    """Read a finished background task's outcome so asyncio does not log it as never retrieved."""
    if not task.cancelled():
        task.exception()


async def run_with_timeout(work: Awaitable[Any], seconds: Optional[float], keep_running: bool) -> Any:
    """Await ``work`` for at most ``seconds``.

    On timeout a read (``keep_running`` False) is cancelled; a write keeps running in the
    background, because cancelling the local call would not stop Revit. Either way
    ToolTimedOut is raised. If the caller itself is cancelled, the work is cancelled too.
    """
    task = asyncio.ensure_future(work)
    if not seconds:
        return await task
    try:
        done, _pending = await asyncio.wait({task}, timeout=seconds)
    except asyncio.CancelledError:
        task.cancel()
        raise
    if task in done:
        return task.result()
    task.add_done_callback(_retrieve)
    if not keep_running:
        task.cancel()
    raise ToolTimedOut(seconds, task, kept_running=keep_running)
