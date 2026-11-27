"""Scope the workspace sandbox to the folders the MCP client has open (roots, issue #202).

Roots only narrow the configured allowed directories (``security.workspace.narrow_directories``);
they never add one. A client that declares no roots capability, or an empty list, is served exactly
as before. Roots are read per session on its first tool call and again after the client sends
``notifications/roots/list_changed``. If the roots cannot be read, the configured directories apply
and a warning is logged. Only ``file`` URIs count; anything else is ignored and logged.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import weakref
from typing import Any
from urllib.parse import unquote, urlsplit

from mcp import types
from mcp.types import ListRootsResult

from .errors import WorkspaceViolation
from .security.workspace import _real, narrow_directories

logger = logging.getLogger(__name__)

FETCH_TIMEOUT_SECONDS = 5.0
_DRIVE_PATH = re.compile(r"^/[A-Za-z]:")
_DRIVE_HOST = re.compile(r"^[A-Za-z]:$")

# session -> real root paths that session declared (None: none declared). Missing: not read yet.
_cache: "weakref.WeakKeyDictionary[Any, tuple[str, ...] | None]" = weakref.WeakKeyDictionary()
# Bumped on every roots/list_changed. A fetch that started before a bump is not stored. The
# notification handler does not know its session, so the counter covers all sessions.
_generation = 0


class _RootsResult(ListRootsResult):
    """roots/list answer that keeps non-file URIs, so they can be ignored one by one."""

    roots: list[Any]


def uri_to_path(uri: Any, windows: "bool | None" = None) -> "str | None":
    """The local path a ``file`` URI names, or None for any other URI. Nothing is resolved here."""
    windows = (os.name == "nt") if windows is None else windows
    try:
        parts = urlsplit(str(uri).strip())
    except ValueError:
        return None
    if parts.scheme.lower() != "file":
        return None
    host = parts.netloc
    path = unquote(parts.path)
    if "\x00" in path or "\x00" in host:
        return None
    if host.lower() == "localhost":
        host = ""
    if _DRIVE_HOST.match(host):  # file://C:/dir, a common malformed form
        path, host = "/" + host + path, ""
    if host or path.startswith(("\\\\", "//")):
        return None  # a network (UNC) share is never a local folder; it is not resolved
    if windows:
        if _DRIVE_PATH.match(path):
            path = path[1:]
        path = path.replace("/", "\\")
        return path if re.match(r"^[A-Za-z]:\\", path) else None
    return path if path.startswith("/") else None


def usable_roots(uris: "list[Any]") -> tuple[str, ...]:
    """Real paths of the ``file`` roots in ``uris``. Others are ignored and logged."""
    found: list[str] = []
    for uri in uris:
        path = uri_to_path(uri)
        if path is None:
            logger.warning("Ignoring client root %r: only local file:// folders are used.", str(uri)[:200])
            continue
        try:
            found.append(_real(path))
        except (WorkspaceViolation, OSError, ValueError):
            logger.warning("Ignoring client root %r: the path cannot be resolved.", str(uri)[:200])
    return tuple(dict.fromkeys(found))


def declares_roots(session: Any) -> bool:
    try:
        return session.client_params.capabilities.roots is not None
    except AttributeError:
        return False


async def for_session(session: Any, monitor: Any = None) -> "tuple[str, ...] | None":
    """Real paths of the roots this session declared, or None when the configured directories apply.

    An empty tuple means roots were declared but none is usable: path tools are refused."""
    if session is None or not declares_roots(session):
        return None
    if session in _cache:
        return _cache[session]
    started = _generation
    try:
        result = await asyncio.wait_for(
            session.send_request(types.ServerRequest(types.ListRootsRequest()), _RootsResult),
            FETCH_TIMEOUT_SECONDS,
        )
        uris = [(r.get("uri") if isinstance(r, dict) else getattr(r, "uri", None)) for r in result.roots]
    except Exception as exc:  # the client may not answer; the configured directories still apply
        logger.warning("Could not read the client's roots (%s); using the configured directories.", type(exc).__name__)
        return None
    roots = usable_roots(uris) if uris else None
    if roots and monitor is not None:
        _, ignored = narrow_directories(
            monitor.allowed_directories, roots, getattr(monitor, "_casefold", None), allowed_resolved=True)
        for root in ignored:
            logger.warning("Ignoring client root %s: it is outside every allowed workspace directory.", root)
    if started == _generation:  # else roots/list_changed landed mid-fetch: read again next call
        _cache[session] = roots
    return roots


async def _on_list_changed(_notification: Any) -> None:
    global _generation
    _generation += 1
    _cache.clear()  # every session reads again on its next call


def register(app: Any) -> None:
    app.notification_handlers[types.RootsListChangedNotification] = _on_list_changed
