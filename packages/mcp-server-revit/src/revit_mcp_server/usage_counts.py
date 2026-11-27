"""Local tool-usage counts for the `learned` profile, and ``aec-model-bridge-usage show|reset``.

What is stored: per tool name, the number of calls per UTC day and the last day it was
used. Nothing else: no arguments, no results, no model data, no user or machine names.
The file is ``<workspace>/usage/tool-usage.json``, built with ``safe_child``. Nothing is
sent anywhere. ``MCP_REVIT_USAGE_COUNTS=off`` turns counting off.

Writes are atomic (temp file, then one replace) and rate limited: calls are counted in
memory and merged into the file at most once per ``FLUSH_INTERVAL_SECONDS`` and when the
server stops. Each flush takes a lock file (``.tool-usage.json.lock``, created with
O_CREAT|O_EXCL, waited on for at most ``LOCK_TIMEOUT_SECONDS``, removed when older than
``STALE_LOCK_SECONDS``), re-reads the file and adds to it, so two server processes on one
workspace do not overwrite each other's counts. When the lock cannot be taken or the
write fails, the counts stay in memory for the next flush.
"""
from __future__ import annotations

import argparse
import atexit
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from .errors import BridgeError
from .security.safe_paths import safe_child

logger = logging.getLogger(__name__)

ENV_VAR = "MCP_REVIT_USAGE_COUNTS"
USAGE_SUBDIR = "usage"
USAGE_NAME = "tool-usage"
USAGE_SUFFIX = ".json"
FORMAT_VERSION = 1
FLUSH_INTERVAL_SECONDS = 60.0
WINDOW_DAYS = 30
KEEP_DAYS = 90  # per-day counts older than this are dropped on write
LOCK_TIMEOUT_SECONDS = 2.0  # longest wait for another process's flush
STALE_LOCK_SECONDS = 30.0  # a lock file older than this is left over from a crash
MAX_TOOLS = 2000  # a file never grows past this many tool names
# Tool names only: letters, digits, underscore, dot, hyphen. Anything else is not counted.
TOOL_NAME_RE = re.compile(r"[A-Za-z0-9_.-]{1,128}")
_OFF = {"", "0", "off", "false", "no", "disabled"}
_ON = {"1", "on", "true", "yes", "enabled"}


def counts_enabled(environ: Optional[Mapping[str, str]] = None) -> bool:
    """True only when MCP_REVIT_USAGE_COUNTS is on (off by default, #273). An unknown value is refused."""
    env = os.environ if environ is None else environ
    value = env.get(ENV_VAR, "").strip().lower()
    if value in _OFF:
        return False
    if value in _ON:
        return True
    raise ValueError(f"{ENV_VAR} must be on or off (got '{env.get(ENV_VAR)}').")


def usage_file(workspace: Any) -> Path:
    """``<workspace>/usage/tool-usage.json``, resolved and checked to stay inside the workspace."""
    def refuse(reason: str) -> Exception:
        return BridgeError(f"The usage counts file would leave the workspace ({reason}); nothing was written.")

    return safe_child(workspace, USAGE_NAME, USAGE_SUFFIX, re.compile(re.escape(USAGE_NAME)),
                      refuse, subdir=USAGE_SUBDIR)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _empty() -> Dict[str, Any]:
    return {"version": FORMAT_VERSION, "tools": {}}


def _clean(data: Any) -> Dict[str, Any]:
    """Keep only well-formed entries: known tool names, ISO days, positive integer counts."""
    out = _empty()
    tools = data.get("tools") if isinstance(data, dict) else None
    if not isinstance(tools, dict):
        return out
    for name, entry in tools.items():
        if not isinstance(name, str) or not TOOL_NAME_RE.fullmatch(name) or not isinstance(entry, dict):
            continue
        days = entry.get("days")
        if not isinstance(days, dict):
            continue
        kept: Dict[str, int] = {}
        for day, count in days.items():
            if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
                continue
            try:
                date.fromisoformat(day)
            except (TypeError, ValueError):
                continue
            kept[day] = count
        if kept:
            out["tools"][name] = {"days": kept, "last_used": max(kept)}
    return out


def load(path: Path) -> Dict[str, Any]:
    """Read the counts file. A missing or unreadable file reads as empty counts."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _empty()
    except OSError as exc:
        logger.warning("Could not read tool usage counts: %s", exc)
        return _empty()
    try:
        return _clean(json.loads(raw))
    except ValueError:
        logger.warning("Tool usage counts file is not valid JSON; starting from zero.")
        return _empty()


def merge(data: Dict[str, Any], pending: Mapping[str, Mapping[str, int]], today: date) -> Dict[str, Any]:
    """Add pending ``{tool: {day: count}}`` to data and drop days older than KEEP_DAYS."""
    out = _clean(data)
    tools = out["tools"]
    for name, days in pending.items():
        if name not in tools and len(tools) >= MAX_TOOLS:
            continue
        entry = tools.setdefault(name, {"days": {}, "last_used": ""})
        for day, count in days.items():
            entry["days"][day] = entry["days"].get(day, 0) + count
    oldest = (today - timedelta(days=KEEP_DAYS)).isoformat()
    for name in list(tools):
        days = {d: c for d, c in tools[name]["days"].items() if d >= oldest}
        if days:
            tools[name] = {"days": dict(sorted(days.items())), "last_used": max(days)}
        else:
            del tools[name]
    out["tools"] = dict(sorted(tools.items()))
    return out


def write_atomic(path: Path, data: Dict[str, Any]) -> None:
    """Write JSON to a temp file next to ``path``, then replace ``path`` in one step."""
    from .security.approval import replace_with_retry

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        replace_with_retry(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


class UsageLockTimeout(Exception):
    """Another process held the counts lock for longer than the wait allows."""


class _FileLock:
    """Interprocess lock: a lock file created with O_CREAT|O_EXCL next to the counts file."""

    def __init__(self, path: Path, timeout: float = LOCK_TIMEOUT_SECONDS,
                 stale_after: float = STALE_LOCK_SECONDS, poll: float = 0.02) -> None:
        self.path = path.with_name(f".{path.name}.lock")
        self.timeout = timeout
        self.stale_after = stale_after
        self.poll = poll

    def __enter__(self) -> "_FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except (FileExistsError, PermissionError):
                # Windows raises PermissionError, not FileExistsError, while the holder is
                # deleting the lock file; both mean another flush is in progress.
                self._remove_if_stale()
                if time.monotonic() >= deadline:
                    raise UsageLockTimeout(f"{self.path.name} is held by another process") from None
                time.sleep(self.poll)
                continue
            try:
                os.write(fd, str(os.getpid()).encode("ascii"))
            finally:
                os.close(fd)
            return self

    def _remove_if_stale(self) -> None:
        try:
            age = time.time() - self.path.stat().st_mtime
        except OSError:
            return  # released meanwhile
        if age > self.stale_after:
            try:
                self.path.unlink()
                logger.warning("Removed a stale tool usage lock file (%.0f s old).", age)
            except OSError:
                pass

    def __exit__(self, *exc: Any) -> None:
        try:
            self.path.unlink()
        except OSError:
            pass


def top_tools(data: Mapping[str, Any], today: Optional[date] = None, days: int = WINDOW_DAYS,
              limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Tools by calls in the last ``days`` days (today included), most used first, then by name."""
    today = today or _today()
    oldest = (today - timedelta(days=days - 1)).isoformat()
    rows = []
    for name, entry in (data.get("tools") or {}).items():
        calls = sum(c for d, c in entry.get("days", {}).items() if d >= oldest)
        if calls > 0:
            rows.append({"name": name, "calls": calls, "last_used": entry.get("last_used")})
    rows.sort(key=lambda r: (-r["calls"], r["name"]))
    return rows if limit is None else rows[:limit]


class UsageCounter:
    """Counts tool calls in memory and flushes them to the counts file, rate limited."""

    def __init__(self, path: Optional[Path], enabled: bool = True,
                 flush_interval: float = FLUSH_INTERVAL_SECONDS,
                 clock: Callable[[], float] = time.monotonic,
                 today: Callable[[], date] = _today,
                 lock_timeout: float = LOCK_TIMEOUT_SECONDS) -> None:
        self.path = path
        self.lock_timeout = lock_timeout
        self.enabled = bool(enabled and path is not None)
        self.flush_interval = flush_interval
        self._clock = clock
        self._today = today
        self._lock = threading.Lock()
        self._pending: Dict[str, Dict[str, int]] = {}
        self._last_flush = clock()

    def record(self, tool_name: str) -> None:
        """Count one call of ``tool_name``. Only the name is taken; a malformed name is ignored."""
        if not self.enabled or not isinstance(tool_name, str) or not TOOL_NAME_RE.fullmatch(tool_name):
            return
        day = self._today().isoformat()
        with self._lock:
            days = self._pending.setdefault(tool_name, {})
            days[day] = days.get(day, 0) + 1
            due = self._clock() - self._last_flush >= self.flush_interval
        if due:
            self.flush()

    def flush(self) -> None:
        """Merge pending counts into the file. Errors are logged, never raised to a tool call."""
        if not self.enabled:
            return
        with self._lock:
            pending, self._pending = self._pending, {}
            self._last_flush = self._clock()
            if not pending:
                return
            try:
                with _FileLock(self.path, timeout=self.lock_timeout):
                    write_atomic(self.path, merge(load(self.path), pending, self._today()))
            except Exception as exc:  # counting must never break a tool call
                logger.warning("Could not write tool usage counts; kept for the next flush: %s", exc)
                self._restore(pending)

    def _restore(self, pending: Mapping[str, Mapping[str, int]]) -> None:
        """Put unwritten counts back into the in-memory buffer (caller holds self._lock)."""
        for name, days in pending.items():
            kept = self._pending.setdefault(name, {})
            for day, count in days.items():
                kept[day] = kept.get(day, 0) + count

    def snapshot(self) -> Dict[str, Any]:
        """File counts plus counts not yet flushed."""
        if self.path is None:
            return _empty()
        with self._lock:
            pending = {k: dict(v) for k, v in self._pending.items()}
        return merge(load(self.path), pending, self._today())


def start_counter(workspace: Any, environ: Optional[Mapping[str, str]] = None) -> UsageCounter:
    """The server's counter: enabled unless opted out, flushed again at process exit."""
    enabled = counts_enabled(environ)
    counter = UsageCounter(usage_file(workspace) if enabled else None, enabled=enabled)
    if enabled:
        atexit.register(counter.flush)
    return counter


# ---- aec-model-bridge-usage ------------------------------------------------- #

def main(argv: Optional[List[str]] = None, workspace: Any = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aec-model-bridge-usage",
        description=("Show or reset the local tool usage counts used by MCP_REVIT_TOOL_PROFILE=learned. "
                     "The counts hold tool names, calls per day and last-used day only, and never leave "
                     "this computer."),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    show = sub.add_parser("show", help="List the most used tools.")
    show.add_argument("--days", type=int, default=WINDOW_DAYS, help=f"Window in days (default {WINDOW_DAYS}).")
    show.add_argument("--limit", type=int, default=25, help="Most rows to print (default 25).")
    show.add_argument("--json", action="store_true", help="Print JSON.")
    sub.add_parser("reset", help="Delete the counts file.")
    args = parser.parse_args(argv)

    if workspace is None:
        from .config import config
        workspace = config.workspace_dir
    path = usage_file(workspace)

    if args.command == "reset":
        if path.exists():
            path.unlink()
            print(f"Deleted {path}")
        else:
            print(f"No counts file at {path}")
        return 0

    if args.days < 1 or args.limit < 1:
        parser.error("--days and --limit must be 1 or more")
    rows = top_tools(load(path), days=args.days, limit=args.limit)
    enabled = counts_enabled()
    if args.json:
        print(json.dumps({"file": str(path), "counting": enabled, "days": args.days, "tools": rows}, indent=2))
        return 0
    print(f"Counts file: {path}")
    print(f"Counting: {'on' if enabled else f'off ({ENV_VAR})'}")
    if not rows:
        print(f"No tool calls counted in the last {args.days} days.")
        return 0
    print(f"Most used tools, last {args.days} days:")
    for row in rows:
        print(f"  {row['calls']:6d}  {row['name']}  (last used {row['last_used']})")
    return 0


def run() -> None:
    try:
        sys.exit(main())
    except (BridgeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    run()
