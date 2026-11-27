"""BCF 3.0 REST topics against a local mock server (UNVERIFIED against real BIMcollab/Revizto)."""
import importlib.util
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from revit_mcp_server.errors import BridgeError
from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security.approval import ApprovalGate
from revit_mcp_server.security.dispatch import gate_before
from revit_mcp_server.security.workspace import WorkspaceMonitor


def _load():
    p = Path(__file__).parent.parent / "src/revit_mcp_server/modules/bcf_exchange/module.py"
    spec = importlib.util.spec_from_file_location("_bcf_rest_impl", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bcf = _load()

TOKEN = "s3cr3t-token-VALUE-123"
PID = "proj-1"
GUID = "3f2b8c1e-0a4d-4c55-9d0e-2b7f5a6c1d10"


class _State:
    topics = {}
    seen = []
    mode = "ok"  # ok | html | redirect | list_as_object


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, payload, ctype="application/json"):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _handle(self, method):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length)) if length else None
        _State.seen.append((method, self.path, self.headers.get("Authorization"), body))
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self._send(401, {"message": f"bad token {self.headers.get('Authorization')}"})
        if _State.mode == "html":
            return self._send(200, b"<html>nope</html>", "text/html")
        if _State.mode == "nested":
            return self._send(200, b"[" * 200000)
        if _State.mode == "badstatus":
            self.wfile.write(b"NOT-HTTP garbage" + bytes([13, 10, 13, 10]))
            return
        if _State.mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/x")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        base = f"/bcf/3.0/projects/{PID}/topics"
        path = self.path.split("?")[0]
        if method == "GET" and path == base:
            if _State.mode == "list_as_object":
                return self._send(200, {"topics": []})
            return self._send(200, list(_State.topics.values()))
        if method == "POST" and path == base:
            topic = {"guid": GUID, "creation_date": "2026-01-01T00:00:00Z", **body}
            _State.topics[GUID] = topic
            return self._send(201, topic)
        if method == "PUT" and path == f"{base}/{GUID}":
            _State.topics[GUID].update(body)
            return self._send(200, _State.topics[GUID])
        return self._send(404, {})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")


@pytest.fixture
def server(monkeypatch):
    _State.topics = {}
    _State.seen = []
    _State.mode = "ok"
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    monkeypatch.setenv("MCP_REVIT_BCF_URL", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setenv("MCP_REVIT_BCF_TOKEN", TOKEN)
    monkeypatch.setenv("MCP_REVIT_BCF_PROJECT_ID", PID)
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def mod():
    return bcf.BcfExchangeModule()


def test_list_create_update(server, mod):
    assert mod.list_server_topics()["topics"] == []
    created = mod.create_server_topic(title="Door clash", priority="High", labels=["qa"], workspace=object(), plan_id="p")
    assert created["status"] == "created"
    assert created["topic"]["guid"] == GUID
    assert _State.seen[-1][3] == {"title": "Door clash", "priority": "High", "labels": ["qa"]}
    updated = mod.update_server_topic(topic_guid=GUID, topic_status="Closed")
    assert updated["topic"]["topic_status"] == "Closed"
    assert updated["topic"]["title"] == "Door clash"
    listed = mod.list_server_topics(project_id=PID, limit=10)
    assert listed["topic_count"] == 1
    assert listed["topics"][0]["topic_status"] == "Closed"
    assert "%24top=10" in _State.seen[-1][1]


def test_missing_token_refused_without_request(server, mod, monkeypatch):
    monkeypatch.delenv("MCP_REVIT_BCF_TOKEN")
    with pytest.raises(bcf.BcfError, match="MCP_REVIT_BCF_TOKEN"):
        mod.list_server_topics()
    with pytest.raises(bcf.BcfError, match="MCP_REVIT_BCF_TOKEN"):
        mod.create_server_topic(title="x")
    assert _State.seen == []


def test_token_is_not_a_tool_argument(server, mod, monkeypatch):
    monkeypatch.delenv("MCP_REVIT_BCF_TOKEN")
    with pytest.raises(bcf.BcfError):
        mod.create_server_topic(title="x", token=TOKEN, bearer_token=TOKEN, authorization=TOKEN)
    assert _State.seen == []
    props = json.loads((Path(bcf.__file__).parent / "module.json").read_text(encoding="utf-8"))
    for cmd in props["commands"]:
        names = set((cmd.get("input_schema") or {}).get("properties", {}))
        assert not {n for n in names if "token" in n or "auth" in n or "url" in n}, cmd["id"]


def test_wrong_token_refused_plainly_and_never_leaked(server, mod, monkeypatch, caplog):
    wrong = "WRONG-token-ABC999"
    monkeypatch.setenv("MCP_REVIT_BCF_TOKEN", wrong)
    caplog.set_level(logging.DEBUG)
    for call in (lambda: mod.list_server_topics(),
                 lambda: mod.create_server_topic(title="x"),
                 lambda: mod.update_server_topic(topic_guid=GUID, title="y")):
        with pytest.raises(bcf.BcfError) as exc:
            call()
        assert "refused the credentials" in str(exc.value)
        assert wrong not in str(exc.value) and wrong not in repr(exc.value)
    assert wrong not in caplog.text


def test_token_never_in_result_or_logs(server, mod, caplog):
    caplog.set_level(logging.DEBUG)
    out = [mod.create_server_topic(title="t"), mod.list_server_topics(), mod.update_server_topic(topic_guid=GUID, title="u")]
    assert TOKEN not in json.dumps(out)
    assert TOKEN not in caplog.text


def test_unreachable_server_error_has_no_token(mod, monkeypatch):
    monkeypatch.setenv("MCP_REVIT_BCF_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("MCP_REVIT_BCF_TOKEN", TOKEN)
    monkeypatch.setenv("MCP_REVIT_BCF_PROJECT_ID", PID)
    with pytest.raises(bcf.BcfError, match="Could not reach") as exc:
        mod.list_server_topics()
    assert TOKEN not in str(exc.value)


def test_non_json_and_wrong_shape_refused(server, mod):
    _State.mode = "html"
    with pytest.raises(bcf.BcfError, match="did not return JSON"):
        mod.list_server_topics()
    _State.mode = "list_as_object"
    with pytest.raises(bcf.BcfError, match="unexpected answer"):
        mod.list_server_topics()


def test_redirect_not_followed(server, mod):
    _State.mode = "redirect"
    with pytest.raises(bcf.BcfError, match="redirect"):
        mod.list_server_topics()
    assert len(_State.seen) == 1


@pytest.mark.parametrize("url", [
    "http://bcf.example.test", "ftp://bcf.example.test", "http://127.0.0.1.evil.test",
    "https://user:pw@bcf.example.test", "https://bcf.example.test?x=1", "bcf.example.test", "",
])
def test_non_https_remote_url_refused(mod, monkeypatch, url):
    monkeypatch.setenv("MCP_REVIT_BCF_TOKEN", TOKEN)
    monkeypatch.setenv("MCP_REVIT_BCF_PROJECT_ID", PID)
    monkeypatch.setenv("MCP_REVIT_BCF_URL", url)
    with pytest.raises(bcf.BcfError, match="MCP_REVIT_BCF_URL|BCF server"):
        mod.list_server_topics()


def test_input_validation(server, mod):
    with pytest.raises(bcf.BcfError, match="title"):
        mod.create_server_topic(description="no title")
    with pytest.raises(bcf.BcfError, match="at least one"):
        mod.update_server_topic(topic_guid=GUID)
    with pytest.raises(bcf.BcfError, match="GUID"):
        mod.update_server_topic(topic_guid="../x", title="a")
    with pytest.raises(bcf.BcfError, match="project_id"):
        mod.list_server_topics(project_id="../../etc")
    with pytest.raises(bcf.BcfError, match="limit"):
        mod.list_server_topics(limit=0)
    with pytest.raises(bcf.BcfError, match="text"):
        mod.create_server_topic(title=["a"])
    assert _State.seen == []


# --- plan gate -------------------------------------------------------------

@pytest.fixture(scope="module")
def registry(tmp_path_factory):
    reg, *_ = build_registry(WorkspaceMonitor([tmp_path_factory.mktemp("bcf-ws")]))
    return reg


def test_create_and_update_are_mutating_list_is_not(registry):
    assert registry.lookup_tool("bcf_exchange_create_server_topic").is_mutating
    assert registry.lookup_tool("bcf_exchange_update_server_topic").is_mutating
    assert not registry.lookup_tool("bcf_exchange_list_server_topics").is_mutating


@pytest.mark.parametrize("tool,args", [
    ("bcf_exchange_create_server_topic", {"title": "x"}),
    ("bcf_exchange_update_server_topic", {"topic_guid": GUID, "title": "x"}),
])
def test_gate_refuses_without_approved_plan(registry, tmp_path, tool, args):
    gate = ApprovalGate(workspace_dir=tmp_path, approval_mode="required")
    with pytest.raises(BridgeError, match="plan_id"):
        gate_before(registry, gate, tool, args)


def test_list_needs_no_plan(registry, tmp_path):
    gate = ApprovalGate(workspace_dir=tmp_path, approval_mode="required")
    assert gate_before(registry, gate, "bcf_exchange_list_server_topics", {}) is None


@pytest.mark.parametrize("mode, match", [("nested", "did not return JSON"), ("badstatus", "malformed HTTP")])
def test_hostile_response_gives_plain_error(server, mod, mode, match):
    _State.mode = mode
    with pytest.raises(bcf.BcfError, match=match):
        mod.list_server_topics()


def test_topic_guid_with_trailing_newline_refused(server, mod):
    with pytest.raises(bcf.BcfError):
        mod.update_server_topic(topic_guid=GUID + chr(10), topic_status="Closed")
    assert _State.seen == []


def test_env_proxy_is_ignored(server, mod, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    assert mod.list_server_topics()["topics"] == []
