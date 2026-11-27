"""Opt-in Streamable HTTP transport for the MCP server (#204).

Off unless MCP_REVIT_HTTP is on. Loopback only, bearer token required. It serves the same
low-level ``Server`` (same tools, same approval gate) as stdio; it adds no handlers of its own.
Threat model: docs/security.md, "Streamable HTTP transport (opt-in)".
"""
from __future__ import annotations

import hmac
import json
import os
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from urllib.parse import urlsplit

LOOPBACK_BIND = "127.0.0.1"
ALLOWED_HOSTS = ("127.0.0.1", "localhost")
ORIGIN_HOSTS = ("127.0.0.1", "localhost", "::1")
DEFAULT_PORT = 8765
MIN_TOKEN_LENGTH = 16
MCP_PATH = "/mcp"

_ON = ("1", "true", "yes", "on")
_OFF = ("", "0", "false", "no", "off")


class HttpConfigError(ValueError):
    """The HTTP transport is configured in a way the server refuses to start with."""


@dataclass(frozen=True)
class HttpSettings:
    host: str
    port: int
    token: str = field(repr=False)


def settings_from_env(env: Mapping[str, str] | None = None) -> HttpSettings | None:
    """None when the transport is off; HttpSettings when explicitly on; HttpConfigError when unsafe."""
    env = os.environ if env is None else env
    flag = env.get("MCP_REVIT_HTTP", "").strip().lower()
    if flag in _OFF:
        return None
    if flag not in _ON:
        raise HttpConfigError("MCP_REVIT_HTTP must be 1 or 0 (also true/false, yes/no, on/off).")

    host = env.get("MCP_REVIT_HTTP_HOST", LOOPBACK_BIND).strip().lower()
    if host not in ALLOWED_HOSTS:
        raise HttpConfigError(
            "MCP_REVIT_HTTP_HOST must be 127.0.0.1 or localhost. The HTTP transport serves this machine only."
        )

    raw_port = env.get("MCP_REVIT_HTTP_PORT", str(DEFAULT_PORT)).strip()
    try:
        port = int(raw_port)
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        raise HttpConfigError("MCP_REVIT_HTTP_PORT must be a port number from 1 to 65535.")

    token = env.get("MCP_REVIT_HTTP_TOKEN", "").strip()
    if len(token) < MIN_TOKEN_LENGTH:
        raise HttpConfigError(
            f"MCP_REVIT_HTTP_TOKEN must be set to a secret of at least {MIN_TOKEN_LENGTH} characters "
            "when MCP_REVIT_HTTP is on."
        )
    return HttpSettings(host=LOOPBACK_BIND, port=port, token=token)


def _host_ok(value: str | None) -> bool:
    if not value:
        return False
    try:
        parts = urlsplit("//" + value)
        parts.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError:
        return False
    return (parts.hostname or "") in ALLOWED_HOSTS and not parts.path and not parts.username


def _origin_ok(value: str) -> bool:
    try:
        parts = urlsplit(value)
        parts.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and (parts.hostname or "") in ORIGIN_HOSTS and not parts.path.strip("/")


def _token_ok(header: str | None, token: str) -> bool:
    if not header:
        return False
    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(presented.strip().encode("utf-8"), token.encode("utf-8"))


class _GuardMiddleware:
    """Host and Origin checks (DNS rebinding), then the bearer token, on every request."""

    def __init__(self, app, token: str):
        self.app = app
        self._token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":  # lifespan passes through; this server has no websockets
            if scope["type"] == "lifespan":
                await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        if not _host_ok(headers.get("host")):
            await _reply(send, 403, {"error": "Forbidden: unexpected Host header"})
        elif "origin" in headers and not _origin_ok(headers["origin"]):
            await _reply(send, 403, {"error": "Forbidden: unexpected Origin header"})
        elif not _token_ok(headers.get("authorization"), self._token):
            await _reply(send, 401, {"error": "Unauthorized"}, {"www-authenticate": "Bearer"})
        else:
            await self.app(scope, receive, send)


async def _reply(send, status: int, body: dict, extra: Mapping[str, str] | None = None) -> None:
    payload = json.dumps(body).encode("utf-8")
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]
    headers += [(k.encode(), v.encode()) for k, v in (extra or {}).items()]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": payload})


def build_asgi_app(server, settings: HttpSettings):
    """Starlette app that serves ``server`` (the low-level MCP Server) at /mcp behind the guard."""
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.routing import Route

    manager = StreamableHTTPSessionManager(
        app=server,
        # Second layer; _GuardMiddleware has already refused anything else.
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[f"{h}:*" for h in ALLOWED_HOSTS] + list(ALLOWED_HOSTS),
            allowed_origins=[f"{scheme}://{h}:*" for scheme in ("http", "https")
                             for h in ("127.0.0.1", "localhost", "[::1]")],
        ),
    )

    class McpEndpoint:  # a class instance is mounted as a raw ASGI app (a bare function would be a GET-only view)
        async def __call__(self, scope, receive, send):
            await manager.handle_request(scope, receive, send)

    @asynccontextmanager
    async def lifespan(_app):
        async with manager.run():
            yield

    return Starlette(
        routes=[Route(MCP_PATH, endpoint=McpEndpoint())],
        middleware=[Middleware(_GuardMiddleware, token=settings.token)],
        lifespan=lifespan,
    )


async def serve(server, settings: HttpSettings) -> None:
    """Listen on 127.0.0.1 until stopped. Refuses any other bind address."""
    if settings.host != LOOPBACK_BIND:
        raise HttpConfigError("The HTTP transport binds 127.0.0.1 only.")
    import uvicorn

    config = uvicorn.Config(
        build_asgi_app(server, settings),
        host=LOOPBACK_BIND,
        port=settings.port,
        log_level="warning",
        access_log=False,
    )
    await uvicorn.Server(config).serve()
