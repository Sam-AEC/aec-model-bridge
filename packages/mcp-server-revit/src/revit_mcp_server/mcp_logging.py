"""Server log messages for the MCP client (``logging/setLevel`` and ``notifications/message``).

A logging handler on the ``revit_mcp_server`` logger sends each record to every client session
that has set a level with ``logging/setLevel``, when the record is at or above that level. A session
that has not set a level receives nothing. The level is kept per session.

Every message passes the same redaction as tool results: secrets and file paths always, personal
data per ``MCP_REVIT_REDACT_RESPONSES``. Only the formatted message is sent, never a traceback.
A failed send is dropped; logging never raises into the tool that logged.
"""
from __future__ import annotations

import asyncio
import logging
import weakref
from contextvars import ContextVar
from typing import Any

from .security.audit import redact_data
from .security.response_redaction import redact_response

PACKAGE_LOGGER = "revit_mcp_server"
MAX_MESSAGE_CHARS = 2000

_sending: ContextVar[bool] = ContextVar("mcp_log_sending", default=False)

# MCP level name -> Python level. notice sits between info and warning; the rest map to CRITICAL.
_PY_LEVELS = {
    "debug": logging.DEBUG, "info": logging.INFO, "notice": logging.INFO + 5, "warning": logging.WARNING,
    "error": logging.ERROR, "critical": logging.CRITICAL, "alert": logging.CRITICAL, "emergency": logging.CRITICAL,
}


def mcp_level(levelno: int) -> str:
    if levelno >= logging.CRITICAL:
        return "critical"
    if levelno >= logging.ERROR:
        return "error"
    if levelno >= logging.WARNING:
        return "warning"
    if levelno >= logging.INFO:
        return "info"
    return "debug"


def safe_message(text: str) -> str:
    """The text a client may see: secrets, paths and (when configured) personal data masked, then cut."""
    text = redact_response(redact_data(text))
    if len(text) > MAX_MESSAGE_CHARS:
        text = text[:MAX_MESSAGE_CHARS] + "..."
    return text


class McpLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        # session -> (python level, event loop that owns the session)
        self._sessions: "weakref.WeakKeyDictionary[Any, tuple[int, asyncio.AbstractEventLoop]]" = (
            weakref.WeakKeyDictionary()
        )
        self._base: tuple[int, int] | None = None  # package logger (own level, effective level) at first use
        self._tasks: set[Any] = set()

    def set_level(self, session: Any, level: str) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._sessions[session] = (_PY_LEVELS.get(level, logging.WARNING), loop)
        self._apply_logger_level()

    def _apply_logger_level(self) -> None:
        # The package logger drops records below its effective level before any handler sees them.
        package = logging.getLogger(PACKAGE_LOGGER)
        if self._base is None:
            self._base = (package.level, package.getEffectiveLevel())
        own, effective = self._base
        wanted = min((lvl for lvl, _ in self._sessions.values()), default=effective)
        package.setLevel(wanted if wanted < effective else own)

    def emit(self, record: logging.LogRecord) -> None:
        if _sending.get():
            return  # a log written while sending must not re-enter
        token = _sending.set(True)
        try:
            targets = [(s, loop) for s, (lvl, loop) in list(self._sessions.items()) if record.levelno >= lvl]
            if not targets:
                return
            message = safe_message(record.getMessage())
            level = mcp_level(record.levelno)
            name = record.name
            for session, loop in targets:
                self._dispatch(session, loop, level, message, name)
        except Exception:  # noqa: BLE001 - logging must never raise into the caller
            self.handleError(record)
        finally:
            _sending.reset(token)

    def _dispatch(self, session: Any, loop: asyncio.AbstractEventLoop, level: str, message: str, name: str) -> None:
        if loop.is_closed():
            return

        async def send() -> None:
            _sending.set(True)
            try:
                await session.send_log_message(level=level, data=message, logger=name)
            except Exception:  # noqa: BLE001 - client gone or stream closed; drop the message
                pass

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            task = loop.create_task(send())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        else:
            asyncio.run_coroutine_threadsafe(send(), loop)


handler = McpLogHandler()


def install() -> None:
    """Attach the handler once. Keeps Python's stderr fallback for warnings when nothing else logs."""
    package = logging.getLogger(PACKAGE_LOGGER)
    if handler in package.handlers:
        return
    if not logging.getLogger().handlers and not package.handlers:
        # An added handler switches off logging.lastResort; keep warnings on stderr as before.
        package.addHandler(logging.lastResort)
    package.addHandler(handler)
