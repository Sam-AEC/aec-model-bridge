"""Cursors for read results the size cap trimmed, and saved files for very large ones.

When ``result_presentation`` trims a read-only result, the full list it cut is kept here, in
memory, under a random id. The answer carries ``cursor``; the same call with
``response_options.cursor`` returns the next part from memory without running the tool again.
A cursor is bound to the tool, its arguments and ``fields``, lasts ``MCP_REVIT_READ_CURSOR_TTL``
seconds (default 600) and lives only in this server process. An unknown, expired or mismatched
cursor is refused with a plain error.

A list too large to keep in memory is written once to ``<workspace>/results/<id>.json`` and the
answer carries ``resource_uri`` (``aec://result/<id>``) instead of a cursor. Only redacted
results reach this module; nothing here runs a tool or touches a model.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .security.safe_paths import safe_child

log = logging.getLogger(__name__)

ENV_MAX_CHARS = "MCP_REVIT_READ_MAX_CHARS"
ENV_TTL = "MCP_REVIT_READ_CURSOR_TTL"
DEFAULT_TTL = 600
MAX_TTL = 3600
MAX_ENTRIES = 32
# A trimmed list longer than this (compact JSON characters) is saved to a file, not kept in memory.
MAX_ENTRY_CHARS = 2_000_000
MAX_TOTAL_CHARS = 16_000_000
MAX_SAVED_RESULTS = 20
RESULTS_DIR = "results"
RESULT_ID_RE = re.compile(r"r[0-9a-f]{24}")
_CURSOR_RE = re.compile(r"rc([0-9a-f]{24})-(\d{1,9})")
PLACEHOLDER_CURSOR = "rc" + "0" * 24 + "-" + "9" * 9
PLACEHOLDER_URI = "aec://result/r" + "0" * 24


class CursorError(ValueError):
    """The cursor is malformed, unknown, expired or belongs to another call."""


def _int_env(name: str, default: int, low: int, high: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        log.warning("Invalid %s=%r; using %s.", name, raw, default)
        return default
    return max(low, min(high, value))


def default_max_chars(fallback: int) -> int:
    """Size cap for read results: MCP_REVIT_READ_MAX_CHARS (0 = off), else ``fallback``. Read on each call."""
    return _int_env(ENV_MAX_CHARS, fallback, 0, 10_000_000)


def cursor_ttl() -> int:
    return _int_env(ENV_TTL, DEFAULT_TTL, 1, MAX_TTL)


def binding(tool: str, arguments: Any, fields: Any) -> str:
    """Hash of what decides the content of a result: tool, arguments (without response_options), fields."""
    canonical = json.dumps({"tool": tool, "arguments": arguments, "fields": fields},
                           sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class Context:
    """What the presenter needs to offer a cursor or a saved file for one call."""
    tool: str
    binding: str
    workspace: Optional[Path] = None
    resource_uri: Optional[str] = None  # set when the full result was saved to a file


@dataclass
class _Entry:
    tool: str
    binding: str
    path: tuple
    items: list
    chars: int
    expires: float


class CursorStore:
    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 max_entries: int = MAX_ENTRIES, max_total_chars: int = MAX_TOTAL_CHARS):
        self._clock = clock
        self._max_entries = max_entries
        self._max_total = max_total_chars
        self._entries: "OrderedDict[str, _Entry]" = OrderedDict()
        self._lock = threading.Lock()

    def _expire(self) -> None:
        now = self._clock()
        for key in [k for k, e in self._entries.items() if e.expires <= now]:
            del self._entries[key]

    def put(self, ctx: Context, path: tuple, items: list, chars: int) -> str:
        key = secrets.token_hex(12)
        with self._lock:
            self._expire()
            self._entries[key] = _Entry(ctx.tool, ctx.binding, path, items, chars, self._clock() + cursor_ttl())
            # Oldest first out: entry count and total size are both capped.
            while len(self._entries) > self._max_entries or (
                    len(self._entries) > 1 and sum(e.chars for e in self._entries.values()) > self._max_total):
                self._entries.popitem(last=False)
        return key

    def get(self, cursor: Any, tool: str, bind: str) -> tuple[_Entry, int, str]:
        match = _CURSOR_RE.fullmatch(cursor) if isinstance(cursor, str) else None
        if not match:
            raise CursorError("response_options.cursor is not a cursor this server issued. "
                              "Call again without a cursor.")
        key, offset = match.group(1), int(match.group(2))
        with self._lock:
            self._expire()
            entry = self._entries.get(key)
        if entry is None:
            raise CursorError(
                f"The cursor has expired or is unknown. Cursors last {cursor_ttl()} seconds and only in the "
                "server process that issued them. Call again without a cursor.")
        if entry.tool != tool or entry.binding != bind:
            raise CursorError(
                f"The cursor belongs to another call ({entry.tool}). Repeat that call's tool, arguments and "
                "fields exactly with the cursor, or call again without a cursor.")
        if offset > len(entry.items):
            raise CursorError("The cursor points past the end of the result. Call again without a cursor.")
        return entry, offset, key

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


STORE = CursorStore()


def make_cursor(key: str, offset: int) -> str:
    return f"rc{key}-{offset}"


def save_result(workspace: Path, result: Any) -> str:
    """Write the full result under <workspace>/results/ and return its resource URI."""
    result_id = "r" + secrets.token_hex(12)

    def refuse(reason: str) -> ValueError:
        return ValueError(f"Cannot save the result ({reason}).")

    path = safe_child(workspace, result_id, ".json", RESULT_ID_RE, refuse, subdir=RESULTS_DIR)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8") as f:
        json.dump(result, f, separators=(",", ":"), default=str)
    _prune(path.parent)
    return f"aec://result/{result_id}"


def _prune(folder: Path) -> None:
    files = [p for p in folder.glob("r*.json") if RESULT_ID_RE.fullmatch(p.stem) and p.is_file() and not p.is_symlink()]
    files.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    for old in files[MAX_SAVED_RESULTS:]:
        try:
            old.unlink()
        except OSError:
            pass


def result_file(workspace: Path, result_id: str) -> Path:
    """Path of a saved result, or ValueError for an id that is not allowed."""
    def refuse(reason: str) -> ValueError:
        return ValueError(f"Result id '{result_id}' is not allowed ({reason}).")

    return safe_child(workspace, result_id, ".json", RESULT_ID_RE, refuse, subdir=RESULTS_DIR)
