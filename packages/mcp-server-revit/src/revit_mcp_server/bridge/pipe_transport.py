"""Opt-in named-pipe transport to the Revit add-in (ADR 0021).

The pipe carries the same JSON as the HTTP bridge. One request per connection:
the client writes one frame, the add-in answers with one frame, then the pipe closes.

Frame: a 4-byte little-endian unsigned length, then that many bytes of UTF-8 JSON.

Request body:  {"method": "GET"|"POST", "path": "/execute", "headers": {"Authorization": "Bearer ..."}, "body": {...}|null}
Response body: {"status": 200, "body": {...}}

The add-in creates the pipe with an ACL for the current Windows user only and publishes its name
as ``pipe_name`` in the Revit registry entry. Windows only; elsewhere the transport refuses.
Live-Revit behaviour is UNVERIFIED.
"""
from __future__ import annotations

import json
import os
import re
import struct
import threading
import time
from typing import Any, BinaryIO, Callable

import httpx

from ..errors import BridgeError

# Same limit as the HTTP listener's request body (BridgeServer.MaxRequestSizeBytes).
MAX_REQUEST_FRAME_BYTES = 5 * 1024 * 1024
# Results can be large (snapshots); the add-in caps a response frame at the same size.
MAX_RESPONSE_FRAME_BYTES = 64 * 1024 * 1024
_HEADER = struct.Struct("<I")
PIPE_NAME_RE = re.compile(r"^AECModelBridge-revit-[0-9]{1,10}-[0-9a-f]{16,64}$")
_ERROR_PIPE_BUSY = 231
_CONNECT_RETRY_SECONDS = 0.05

TRANSPORTS = ("http", "pipe")
PLATFORM = os.name  # read through this name so tests can stand in for Windows


class PipeProtocolError(httpx.RemoteProtocolError):
    """A frame was malformed, truncated or too large."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


def resolve_transport(configured: str | None) -> str:
    """Return 'http' or 'pipe'. MCP_REVIT_BRIDGE_TRANSPORT wins, then AEC_BRIDGE_TRANSPORT, then 'http'.

    An unknown value raises BridgeError: it is never guessed to mean either transport."""
    raw = configured if configured not in (None, "") else os.environ.get("AEC_BRIDGE_TRANSPORT", "")
    value = str(raw).strip().lower() or "http"
    if value not in TRANSPORTS:
        raise BridgeError(
            f"Unknown bridge transport {raw!r}. Set MCP_REVIT_BRIDGE_TRANSPORT to 'http' or 'pipe', or unset it."
        )
    return value


def require_windows(platform: str | None = None) -> None:
    """Refuse the pipe transport off Windows with a plain error."""
    if (platform or PLATFORM) != "nt":
        raise BridgeError(
            "The named-pipe bridge transport works only on Windows. "
            "Set MCP_REVIT_BRIDGE_TRANSPORT to 'http' or unset it."
        )


def encode_frame(message: Any, max_bytes: int) -> bytes:
    """Serialize ``message`` as one frame. Refuses a frame larger than ``max_bytes``."""
    data = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(data) > max_bytes:
        raise PipeProtocolError(f"Frame of {len(data)} bytes exceeds the {max_bytes}-byte limit.")
    return _HEADER.pack(len(data)) + data


def _read_exact(stream: BinaryIO, count: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < count:
        chunk = stream.read(count - len(chunks))
        if not chunk:
            raise PipeProtocolError(
                f"The pipe closed after {len(chunks)} of {count} bytes; the frame is incomplete."
            )
        chunks.extend(chunk)
    return bytes(chunks)


def read_frame(stream: BinaryIO, max_bytes: int) -> Any:
    """Read one frame. Refuses a declared length above ``max_bytes`` before reading the body."""
    (length,) = _HEADER.unpack(_read_exact(stream, _HEADER.size))
    if length > max_bytes:
        raise PipeProtocolError(f"Frame of {length} bytes exceeds the {max_bytes}-byte limit.")
    data = _read_exact(stream, length)
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise PipeProtocolError(f"Frame is not valid UTF-8 JSON: {e}") from e


def build_request(method: str, path: str, token: str | None, body: Any = None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return {"method": method, "path": path, "headers": headers, "body": body}


def parse_response(message: Any) -> tuple[int, Any]:
    if not isinstance(message, dict) or not isinstance(message.get("status"), int) or isinstance(message.get("status"), bool):
        raise PipeProtocolError("Pipe response is not an object with an integer 'status'.")
    return message["status"], message.get("body")


def exchange(stream: BinaryIO, request: dict[str, Any]) -> tuple[int, Any]:
    """Write one request frame and read one response frame on an open stream."""
    stream.write(encode_frame(request, MAX_REQUEST_FRAME_BYTES))
    flush = getattr(stream, "flush", None)
    if flush is not None:
        flush()
    return parse_response(read_frame(stream, MAX_RESPONSE_FRAME_BYTES))


def _windows_open(path: str) -> BinaryIO:  # pragma: no cover - Windows only
    """Open a pipe client handle with CreateFileW so a failure keeps its Win32 code.

    The built-in open() goes through _wopen and builds its OSError from errno, which loses
    ERROR_PIPE_BUSY (231); the busy-pipe retry in _connect needs ``winerror`` (#281 review)."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel32.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    generic_read_write = 0x80000000 | 0x40000000
    open_existing = 3
    handle = create(path, generic_read_write, 0, None, open_existing, 0, None)
    if handle is None or handle == ctypes.c_void_p(-1).value:
        # WinError(2) is a FileNotFoundError; WinError(231) keeps winerror == 231.
        raise ctypes.WinError(ctypes.get_last_error())
    fd = msvcrt.open_osfhandle(handle, os.O_RDWR | getattr(os, "O_BINARY", 0))
    return os.fdopen(fd, "r+b", buffering=0)


def _windows_server_pid(stream: Any) -> int | None:
    """Process id of the pipe server, or None if it cannot be read."""
    try:
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(stream.fileno())
        pid = ctypes.c_ulong()
        if ctypes.windll.kernel32.GetNamedPipeServerProcessId(ctypes.c_void_p(handle), ctypes.byref(pid)):
            return int(pid.value)
    except Exception:
        return None
    return None


class PipeTransport:
    """Client side of the pipe. Raises httpx.RequestError subclasses on transport failures so the
    BridgeClient's retry and polling rules apply unchanged."""

    def __init__(
        self,
        pipe_name: str,
        expected_pid: int | None,
        timeout: float = 30,
        *,
        opener: Callable[[str], BinaryIO] | None = None,
        server_pid: Callable[[Any], int | None] | None = None,
        platform: str | None = None,
    ) -> None:
        require_windows(platform)
        if not isinstance(pipe_name, str) or not PIPE_NAME_RE.match(pipe_name):
            raise BridgeError(
                "The Revit registry entry has an invalid pipe name. Restart Revit, or use the HTTP transport."
            )
        self.pipe_name = pipe_name
        self.path = "\\\\.\\pipe\\" + pipe_name
        self.expected_pid = expected_pid
        self.timeout = float(timeout)
        self._opener = opener or _windows_open
        self._server_pid = server_pid or _windows_server_pid
        self._sleep = time.sleep
        self._clock = time.monotonic

    def url(self, path: str) -> str:
        return f"pipe://{self.pipe_name}{path}"

    def _connect(self) -> BinaryIO:
        deadline = self._clock() + min(self.timeout, 5.0)
        while True:
            try:
                return self._opener(self.path)
            except FileNotFoundError as e:
                raise httpx.ConnectError(f"Revit bridge pipe {self.pipe_name} does not exist: {e}") from e
            except OSError as e:
                busy = getattr(e, "winerror", None) == _ERROR_PIPE_BUSY
                if not busy or self._clock() >= deadline:
                    raise httpx.ConnectError(f"Cannot open Revit bridge pipe {self.pipe_name}: {e}") from e
                self._sleep(_CONNECT_RETRY_SECONDS)

    def _check_server(self, stream: Any) -> None:
        if self.expected_pid is None:
            return
        actual = self._server_pid(stream)
        if actual != self.expected_pid:
            raise BridgeError(
                f"The pipe {self.pipe_name} is served by process {actual}, not by the Revit process "
                f"{self.expected_pid} named in the registry. No token was sent. Restart Revit."
            )

    @staticmethod
    def _close(stream: Any) -> None:
        try:
            stream.close()
        except OSError:
            pass

    def request(self, method: str, path: str, token: str | None, body: Any = None) -> tuple[int, Any]:
        stream = self._connect()
        try:
            self._check_server(stream)
        except BaseException:
            self._close(stream)
            raise
        outcome: dict[str, Any] = {}

        def run() -> None:
            # The worker owns the stream and closes it. Closing a handle while another thread
            # reads it can block on Windows, so a timed-out caller never closes it.
            try:
                outcome["value"] = exchange(stream, build_request(method, path, token, body))
            except BaseException as e:  # handed to the caller below
                outcome["error"] = e
            finally:
                self._close(stream)

        worker = threading.Thread(target=run, name="aec-pipe-request", daemon=True)
        worker.start()
        worker.join(self.timeout)
        if worker.is_alive():
            raise httpx.ReadTimeout(f"No answer on pipe {self.pipe_name} within {self.timeout:g} s.")
        if "error" in outcome:
            error = outcome["error"]
            if isinstance(error, (httpx.RequestError, BridgeError)):
                raise error
            if isinstance(error, OSError):
                raise httpx.ReadError(f"Pipe {self.pipe_name} failed: {error}") from error
            raise error
        return outcome["value"]
