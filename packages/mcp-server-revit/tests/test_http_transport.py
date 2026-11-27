"""Opt-in Streamable HTTP transport (#204): off by default, loopback only, bearer token, Origin/Host checks.

Requests go through the ASGI app in process with httpx; no port is opened.
"""
from __future__ import annotations

import asyncio
import json
import socket

import httpx
import pytest

from revit_mcp_server import http_transport, mcp_server
from revit_mcp_server.http_transport import HttpConfigError, HttpSettings, settings_from_env
from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.tool_profiles import load_tool_profile

TOKEN = "t0ken-" + "x" * 30
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
JSON_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def _env(**over):
    env = {"MCP_REVIT_HTTP": "1", "MCP_REVIT_HTTP_TOKEN": TOKEN}
    env.update(over)
    return {k: v for k, v in env.items() if v is not None}


# ---- settings: off by default, fail closed ---------------------------------------------------------

@pytest.mark.parametrize("env", [{}, {"MCP_REVIT_HTTP": ""}, {"MCP_REVIT_HTTP": "0"}, {"MCP_REVIT_HTTP": "off"},
                                 {"MCP_REVIT_HTTP_TOKEN": TOKEN}])
def test_off_by_default(env):
    assert settings_from_env(env) is None


@pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
def test_explicit_opt_in_values(value):
    settings = settings_from_env(_env(MCP_REVIT_HTTP=value))
    assert settings == HttpSettings(host="127.0.0.1", port=PORT, token=TOKEN)


def test_unknown_enable_value_is_refused():
    with pytest.raises(HttpConfigError, match="MCP_REVIT_HTTP"):
        settings_from_env(_env(MCP_REVIT_HTTP="maybe"))


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.5", "example.com", "::1", "127.0.0.2", ""])
def test_non_loopback_host_is_refused(host):
    with pytest.raises(HttpConfigError, match="MCP_REVIT_HTTP_HOST"):
        settings_from_env(_env(MCP_REVIT_HTTP_HOST=host))


def test_localhost_binds_the_ipv4_loopback_address():
    assert settings_from_env(_env(MCP_REVIT_HTTP_HOST="localhost")).host == "127.0.0.1"


@pytest.mark.parametrize("token", [None, "", "   ", "short"])
def test_missing_or_weak_token_is_refused(token):
    with pytest.raises(HttpConfigError, match="MCP_REVIT_HTTP_TOKEN"):
        settings_from_env(_env(MCP_REVIT_HTTP_TOKEN=token))


@pytest.mark.parametrize("port", ["0", "70000", "abc", "-1", ""])
def test_bad_port_is_refused(port):
    with pytest.raises(HttpConfigError, match="MCP_REVIT_HTTP_PORT"):
        settings_from_env(_env(MCP_REVIT_HTTP_PORT=port))


def test_token_never_appears_in_repr_or_errors():
    settings = settings_from_env(_env())
    assert TOKEN not in repr(settings) and TOKEN not in str(settings)
    with pytest.raises(HttpConfigError) as err:
        settings_from_env(_env(MCP_REVIT_HTTP_HOST="0.0.0.0"))
    assert TOKEN not in str(err.value)


# ---- startup: nothing listens unless enabled -------------------------------------------------------

def _fake_stdio(monkeypatch):
    from contextlib import asynccontextmanager

    ran = []

    @asynccontextmanager
    async def fake_stdio_server():
        yield ("read", "write")

    async def fake_run(read, write, options):
        ran.append((read, write))

    monkeypatch.setattr(mcp_server, "stdio_server", fake_stdio_server)
    monkeypatch.setattr(mcp_server.app, "run", fake_run)
    return ran


def _forbid_listening(monkeypatch, serve=True):
    def refuse(*a, **k):
        raise AssertionError("a socket was bound or a server was started")

    import uvicorn

    monkeypatch.setattr(socket.socket, "bind", refuse)
    monkeypatch.setattr(socket.socket, "listen", refuse)
    monkeypatch.setattr(uvicorn.Server, "serve", refuse)
    if serve:
        monkeypatch.setattr(http_transport, "serve", refuse)


def _run_with_no_listening(monkeypatch, coro_fn, serve=True):
    # Create the loop first: a Windows event loop binds a local socketpair when it is created.
    loop = asyncio.new_event_loop()
    try:
        _forbid_listening(monkeypatch, serve=serve)
        return loop.run_until_complete(coro_fn())
    finally:
        loop.close()


def test_off_opens_no_socket_and_uses_stdio(monkeypatch):
    for name in ("MCP_REVIT_HTTP", "MCP_REVIT_HTTP_TOKEN", "MCP_REVIT_HTTP_HOST", "MCP_REVIT_HTTP_PORT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MCP_REVIT_HTTP_TOKEN", TOKEN)  # a token alone does not enable it
    ran = _fake_stdio(monkeypatch)
    _run_with_no_listening(monkeypatch, mcp_server.main)
    assert ran == [("read", "write")]


@pytest.mark.parametrize("env", [{"MCP_REVIT_HTTP_HOST": "0.0.0.0"}, {"MCP_REVIT_HTTP_TOKEN": ""}])
def test_bad_http_settings_fail_before_providers_or_sockets(monkeypatch, env):
    for name, value in _env(**env).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(mcp_server, "build_registry", lambda: pytest.fail("providers built before validation"))
    with pytest.raises(HttpConfigError):
        _run_with_no_listening(monkeypatch, mcp_server.main)


def test_enabled_serves_http_instead_of_stdio(monkeypatch):
    for name, value in _env().items():
        monkeypatch.setenv(name, value)
    ran = _fake_stdio(monkeypatch)
    served = []

    async def fake_serve(server, settings):
        served.append((server, settings))

    monkeypatch.setattr(http_transport, "serve", fake_serve)
    asyncio.run(mcp_server.main())
    assert served == [(mcp_server.app, HttpSettings(host="127.0.0.1", port=PORT, token=TOKEN))]
    assert ran == []


def test_uvicorn_is_bound_to_loopback_only(monkeypatch):
    import uvicorn

    seen = {}

    async def fake_serve(self, *a, **k):
        seen["host"], seen["port"] = self.config.host, self.config.port

    monkeypatch.setattr(uvicorn.Server, "serve", fake_serve)
    asyncio.run(http_transport.serve(mcp_server.app, HttpSettings("127.0.0.1", 9999, TOKEN)))
    assert seen == {"host": "127.0.0.1", "port": 9999}


def test_serve_refuses_a_non_loopback_settings_object(monkeypatch):
    # Defence in depth: even a hand-built settings object cannot make serve() bind elsewhere.
    with pytest.raises(HttpConfigError):
        _run_with_no_listening(monkeypatch, lambda: http_transport.serve(
            mcp_server.app, HttpSettings("0.0.0.0", PORT, TOKEN)), serve=False)


# ---- requests through the ASGI app ----------------------------------------------------------------

@pytest.fixture
def live_registry(monkeypatch):
    registry, approval_provider, job_manager, _modules, monitor = build_registry()
    registry.freeze_tool_profile(load_tool_profile())
    monkeypatch.setattr(mcp_server, "registry", registry)
    monkeypatch.setattr(mcp_server, "approval_provider", approval_provider)
    monkeypatch.setattr(mcp_server, "job_manager", job_manager)
    yield registry
    asyncio.run(job_manager.shutdown(cancel_running=True))


def _run(coro_fn):
    """Run ``coro_fn(client)`` against a fresh app with its lifespan started."""
    async def go():
        asgi = http_transport.build_asgi_app(mcp_server.app, HttpSettings("127.0.0.1", PORT, TOKEN))
        async with asgi.router.lifespan_context(asgi):
            transport = httpx.ASGITransport(app=asgi)
            async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
                return await coro_fn(client)

    return asyncio.run(go())


def _auth(token=TOKEN, **extra):
    return {**JSON_HEADERS, "Authorization": f"Bearer {token}", **extra}


def _rpc(method, id_=1, **params):
    msg = {"jsonrpc": "2.0", "method": method, "params": params}
    if id_ is not None:
        msg["id"] = id_
    return msg


def _body(response):
    text = response.text
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        datas = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")]
        return json.loads(datas[-1])
    return json.loads(text)


WALL = {"start_x": 0, "start_y": 0, "end_x": 5, "end_y": 0}
INIT = _rpc("initialize", protocolVersion="2025-03-26", capabilities={},
            clientInfo={"name": "pytest", "version": "0"})


async def _open_session(client):
    r = await client.post("/mcp", json=INIT, headers=_auth())
    assert r.status_code == 200, r.text
    sid = r.headers["mcp-session-id"]
    headers = _auth(**{"mcp-session-id": sid})
    r2 = await client.post("/mcp", json=_rpc("notifications/initialized", id_=None), headers=headers)
    assert r2.status_code == 202
    return headers


def test_missing_token_gets_401():
    async def go(client):
        r = await client.post("/mcp", json=INIT, headers=JSON_HEADERS)
        assert r.status_code == 401
        assert r.headers["www-authenticate"].startswith("Bearer")
        return r

    r = _run(go)
    assert TOKEN not in r.text


@pytest.mark.parametrize("header", ["Bearer wrong-token-wrong-token-wrong", "Bearer ", "Basic " + "x" * 40,
                                    "Bearer", TOKEN, "bearer " + TOKEN.upper()])
def test_wrong_token_gets_401(header):
    async def go(client):
        return await client.post("/mcp", json=INIT, headers={**JSON_HEADERS, "Authorization": header})

    r = _run(go)
    assert r.status_code == 401
    assert TOKEN not in r.text


def test_missing_and_wrong_token_answers_are_identical():
    async def go(client):
        a = await client.post("/mcp", json=INIT, headers=JSON_HEADERS)
        b = await client.post("/mcp", json=INIT, headers=_auth("nope" * 10))
        return a, b

    a, b = _run(go)
    assert (a.status_code, a.text) == (b.status_code, b.text)


def test_other_paths_need_the_token_too():
    async def go(client):
        no = await client.get("/anything")
        yes = await client.get("/anything", headers={"Authorization": f"Bearer {TOKEN}"})
        return no, yes

    no, yes = _run(go)
    assert no.status_code == 401
    assert yes.status_code == 404


def test_token_is_compared_in_constant_time(monkeypatch):
    calls = []
    real = http_transport.hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(http_transport.hmac, "compare_digest", spy)

    async def go(client):
        return await client.post("/mcp", json=INIT, headers=_auth("wrong" * 8))

    assert _run(go).status_code == 401
    assert calls


def test_good_token_initializes_and_lists_tools(live_registry):
    async def go(client):
        headers = await _open_session(client)
        r = await client.post("/mcp", json=_rpc("tools/list", 2), headers=headers)
        assert r.status_code == 200
        return _body(r)

    body = _run(go)
    names = {t["name"] for t in body["result"]["tools"]}
    assert "revit_get_context" in names
    assert names == {t.name for t in asyncio.run(mcp_server.list_tools())}


def test_write_tool_over_http_is_refused_by_the_approval_gate(live_registry):
    async def go(client):
        headers = await _open_session(client)
        r = await client.post("/mcp", json=_rpc("tools/call", 3, name="revit_create_wall", arguments=WALL),
                              headers=headers)
        return _body(r)

    body = _run(go)
    result = body["result"]
    assert result["isError"] is True
    assert "plan" in json.dumps(result).lower()


def test_http_and_direct_calls_share_the_gate(live_registry, monkeypatch):
    seen = []
    real = mcp_server.gate_before

    def spy(*a, **k):
        seen.append(a[0] if a else k)
        return real(*a, **k)

    monkeypatch.setattr(mcp_server, "gate_before", spy)

    async def go(client):
        headers = await _open_session(client)
        await client.post("/mcp", json=_rpc("tools/call", 4, name="revit_create_wall", arguments=WALL),
                          headers=headers)

    _run(go)
    assert seen, "gate_before was not consulted for a tool call over HTTP"


@pytest.mark.parametrize("origin", ["https://evil.example", "http://evil.example:8765", "null",
                                    "http://127.0.0.1.evil.example", "ftp://127.0.0.1", "http://localhost.evil.test"])
def test_foreign_origin_is_rejected_even_with_the_token(origin):
    async def go(client):
        return await client.post("/mcp", json=INIT, headers=_auth(Origin=origin))

    assert _run(go).status_code == 403


@pytest.mark.parametrize("origin", ["http://127.0.0.1:8765", "http://localhost:6274", "http://[::1]:3000"])
def test_loopback_origin_is_accepted(origin):
    async def go(client):
        return await client.post("/mcp", json=INIT, headers=_auth(Origin=origin))

    assert _run(go).status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8765", "127.0.0.1.evil.example",
                                  "192.168.1.5:8765", "localhost.evil.test"])
def test_foreign_host_header_is_rejected(host):
    async def go(client):
        return await client.post("/mcp", json=INIT, headers=_auth(Host=host))

    assert _run(go).status_code == 403


def test_origin_and_host_checks_run_before_the_token_check():
    async def go(client):
        return await client.post("/mcp", json=INIT, headers={**JSON_HEADERS, "Origin": "https://evil.example"})

    assert _run(go).status_code == 403
