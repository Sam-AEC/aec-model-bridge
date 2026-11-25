"""MCP Apps plan review view (ui://aec-model-bridge/plan-review): read-only, escaped, never an approval path."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp import ClientSession, types
from mcp.shared import memory

from revit_mcp_server import mcp_apps, mcp_resources, mcp_server
from revit_mcp_server.config import config
from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security.approval import ApprovalGate, HUMAN_ONLY_TOOLS
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.tool_metadata import ALWAYS_LOAD_META_KEY
from revit_mcp_server.tool_profiles import ALWAYS_LOADED_TOOLS

XSS = "<script>alert('x')</script>"


@pytest.fixture
def gate(tmp_path):
    return ApprovalGate(workspace_dir=tmp_path, approval_mode="ask_first")


@pytest.fixture
def apps_on(monkeypatch):
    monkeypatch.setattr(config, "mcp_apps", "always")


@pytest.fixture
def apps_off(monkeypatch):
    monkeypatch.setattr(config, "mcp_apps", "off")


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """mcp_server wired to a real registry (mock mode) and a temporary workspace."""
    workspace_dir = Path(tmp_path_factory.mktemp("apps-ws"))
    monitor = WorkspaceMonitor([workspace_dir])
    registry, approval, job_manager, _modules, _ws = build_registry(monitor)
    names = ("registry", "approval_provider", "job_manager", "workspace_monitor")
    previous = tuple(getattr(mcp_server, n) for n in names)
    for n, v in zip(names, (registry, approval, job_manager, monitor)):
        setattr(mcp_server, n, v)
    try:
        yield registry, approval
    finally:
        for n, v in zip(names, previous):
            setattr(mcp_server, n, v)


def _xss_plan(gate):
    return gate.create_plan(
        [{"tool": "revit_set_parameter_value",
          "arguments": {"element_id": XSS, "name": XSS, "parameter_name": "<img src=x onerror=alert(1)>",
                        "value": "</script><b>bold</b>"}}],
        [{XSS: {"<img src=x onerror=alert(1)>": "a & <i>b</i>"}}],
        review={"summary": f"Rename {XSS}", "warnings": [f"Check {XSS}"]},
    )


class _RawElements(HTMLParser):
    """Collects every <script> and <style> element as (tag, attributes, raw text). The parser
    matches tag names in any letter case, as a browser does."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.found: list = []
        self._open = None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._open = (tag, dict(attrs), [])

    def handle_data(self, data):
        if self._open is not None:
            self._open[2].append(data)

    def handle_endtag(self, tag):
        if self._open is not None and tag == self._open[0]:
            self.found.append((tag, self._open[1], "".join(self._open[2])))
            self._open = None


def _elements(html, tag):
    parser = _RawElements()
    parser.feed(html)
    parser.close()
    return [(attrs, text) for name, attrs, text in parser.found if name == tag]


def _scripts(html):
    """(attributes, text) of every script element, in page order."""
    return _elements(html, "script")


# ---- resource listing and reading ------------------------------------------

def test_view_resource_listed_with_mcp_apps_mime_and_meta(apps_on):
    listed = {str(r.uri): r for r in mcp_resources.list_resources()}
    view = listed[mcp_apps.PLAN_REVIEW_URI]
    assert view.mimeType == "text/html;profile=mcp-app"
    assert view.meta["ui"]["csp"] == {"connectDomains": [], "resourceDomains": []}
    templates = {t.uriTemplate: t for t in mcp_resources.list_resource_templates()}
    assert templates[mcp_apps.PLAN_REVIEW_TEMPLATE].mimeType == mcp_apps.MIME


def test_view_resource_readable_through_server(apps_on, tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "approval_provider", type("A", (), {"gate": ApprovalGate(tmp_path)})())
    contents = asyncio.run(mcp_server.read_resource(mcp_apps.PLAN_REVIEW_URI))
    assert contents[0].mime_type == mcp_apps.MIME
    assert contents[0].content.startswith("<!doctype html>")
    assert contents[0].meta["ui"]["csp"]["connectDomains"] == []
    assert "aec-model-bridge-approve approve" in contents[0].content


def test_per_plan_view_embeds_the_plan(apps_on, gate):
    plan = gate.create_plan(
        [{"tool": "revit_set_parameter_value", "arguments": {"element_id": 7, "parameter_name": "Mark", "value": "B"}}],
        [{"7": {"Mark": "A"}}])
    html, meta = mcp_apps.read_resource(f"ui://aec-model-bridge/plan-review/{plan['plan_id']}", gate)
    attrs, data = _scripts(html)[0]
    assert attrs.get("type") == "application/json"
    embedded = json.loads(data)
    assert embedded["approval_mode"] == "ask_first"
    shown = embedded["plans"][0]
    assert shown["plan_id"] == plan["plan_id"] and shown["plan_hash"] == plan["plan_hash"]
    assert shown["preview"]["rows"][0]["before"] == "A" and shown["preview"]["rows"][0]["after"] == "B"
    assert meta == mcp_apps.resource_meta()


@pytest.mark.parametrize("uri", [
    "ui://aec-model-bridge/plan-review/../plans/x", "ui://aec-model-bridge/plan-review/plan_1",
    "ui://aec-model-bridge/plan-review/plan_000000000000", "ui://aec-model-bridge/other",
    "ui://aec-model-bridge/plan-review/a/b", "ui://evil/plan-review",
])
def test_bad_view_uris_refused(apps_on, uri, gate):
    with pytest.raises(mcp_apps.AppsResourceError):
        mcp_apps.read_resource(uri, gate)


# ---- escaping and no network ----------------------------------------------

def test_model_text_is_escaped(apps_on, gate):
    plan = _xss_plan(gate)
    html, _ = mcp_apps.read_resource(f"ui://aec-model-bridge/plan-review/{plan['plan_id']}", gate)
    # Exactly two script elements: the inert JSON data block and the view's own code. Tags are
    # matched in any letter case, so an injected <SCRIPT> would be counted too.
    scripts = _scripts(html)
    assert [attrs.get("type") for attrs, _ in scripts] == ["application/json", None]
    assert scripts[1][1] == mcp_apps._SCRIPT
    lowered = html.lower()
    assert lowered.count("<script") == 2 and lowered.count("</script") == 2
    for raw in ("<script>alert", "<img src=x", "<b>bold", "<i>b</i>", "onerror=alert(1)>"):
        assert raw not in html
    data = _scripts(html)[0][1]
    assert "<" not in data and ">" not in data and "&" not in data
    assert "alert('x')" in json.loads(data)["plans"][0]["review"]["summary"]


def test_view_code_renders_text_only():
    code = mcp_apps._SCRIPT
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function",
                   "setAttribute(\"on", "javascript:"):
        assert banned not in code, banned
    assert "textContent" in code


def test_view_loads_nothing_from_the_network(apps_on, gate):
    plan = _xss_plan(gate)
    for html in (mcp_apps.render_html(None),
                 mcp_apps.read_resource(f"ui://aec-model-bridge/plan-review/{plan['plan_id']}", gate)[0]):
        # The page without its inert JSON data block (model text there is checked as escaped above).
        data = [text for attrs, text in _scripts(html) if attrs.get("type") == "application/json"]
        page = html.replace(data[0], "", 1) if data else html
        assert not re.search(r"https?:|wss?:|//[a-z0-9]", page, flags=re.I)
        for banned in (" src=", " href=", "@import", "url(", "fetch(", "XMLHttpRequest", "WebSocket",
                       "<iframe", "<link", "<img", "<form"):
            assert banned.lower() not in page.lower(), banned


def test_csp_allows_only_the_inline_code_by_hash():
    html = mcp_apps.render_html(None)
    csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html).group(1)
    code = _scripts(html)[-1][1]
    style = _elements(html, "style")[0][1]

    def digest(text):
        return "sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()

    assert f"script-src '{digest(code)}'" in csp and f"style-src '{digest(style)}'" in csp
    for part in ("default-src 'none'", "connect-src 'none'", "frame-src 'none'", "form-action 'none'"):
        assert part in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert " style=" not in html  # inline style attributes would need unsafe-inline


# ---- no approval from the view ---------------------------------------------

def test_view_offers_no_approval_control():
    html = mcp_apps.render_html(None)
    code = mcp_apps._SCRIPT
    # The only control is "Copy plan id".
    assert re.findall(r'el\("button", null, "([^"]+)"\)', code) == ["Copy plan id"]
    for banned in ("tools/call", "ui/message", "ui/open-link", "approve_plan", "reject_plan", "rollback_plan",
                   "execute_plan", "plan_actions", "resources/read", "sampling"):
        assert banned not in html, banned
    sent = set(re.findall(r'(?:request|notify)\("([^"]+)"', code))
    assert sent == {"ui/initialize", "ui/notifications/initialized", "ui/notifications/size-changed"}
    assert "This view cannot approve, reject or run a plan." in code
    assert "Approve in the Revit panel" in code


def test_tool_meta_restricts_apps_to_read_only_tools(apps_on, server):
    registry, _ = server
    tools = {t.name: t for t in asyncio.run(mcp_server.list_tools())}
    assert not HUMAN_ONLY_TOOLS & set(tools)
    for name in ("plan_actions", "list_pending_plans"):
        assert tools[name].meta["ui"] == {"resourceUri": mcp_apps.PLAN_REVIEW_URI, "visibility": ["model"]}
    assert tools["execute_plan"].meta["ui"] == {"visibility": ["model"]}
    raw = {t.name: t for t in registry.get_all_tools()}
    for name, tool in tools.items():
        ui = (tool.meta or {}).get("ui")
        if mcp_apps.is_read_only(raw[name]) and name not in mcp_apps.PLAN_VIEW_TOOLS:
            assert ui is None, name
        else:
            assert ui["visibility"] == ["model"], name
    # Existing _meta keys are kept next to "ui".
    for name in set(ALWAYS_LOADED_TOOLS) & set(tools):
        assert tools[name].meta[ALWAYS_LOAD_META_KEY] is True, name
    assert set(ALWAYS_LOADED_TOOLS) & {n for n, t in tools.items() if "ui" in (t.meta or {})}


@pytest.mark.parametrize("name", sorted(HUMAN_ONLY_TOOLS))
def test_approval_tools_refused_on_any_tool_call(apps_on, server, name, tmp_path):
    # A host proxies an app's tools/call to the server as an ordinary call; it is refused like any other.
    result = asyncio.run(mcp_server.call_tool(name, {"plan_id": "plan_000000000000"}))
    assert result.isError
    assert "not available to AI clients" in result.content[0].text


def test_plan_results_carry_the_approval_mode_in_meta_only(apps_on, server):
    _, approval = server
    key = mcp_apps.APPROVAL_MODE_META_KEY
    listing = asyncio.run(mcp_server.call_tool("list_pending_plans", {}))
    assert listing.meta == {key: approval.gate.approval_mode}
    assert "approval_mode" not in listing.structuredContent
    action = {"tool": "revit_create_level", "arguments": {"name": "L9", "elevation": 30}}
    drafted = asyncio.run(mcp_server.call_tool("plan_actions", {"actions": [action]}))
    assert drafted.meta == {key: approval.gate.approval_mode}
    plan = json.loads(drafted.content[0].text.split("Result:\n")[1])
    assert "approval_mode" not in plan
    # Other tools get no _meta.
    other = asyncio.run(mcp_server.call_tool("policy_show", {}))
    assert getattr(other, "meta", None) is None
    assert key in mcp_apps._SCRIPT


def test_flag_off_leaves_plan_results_plain(apps_off, server):
    drafted = asyncio.run(mcp_server.call_tool("plan_actions", {
        "actions": [{"tool": "revit_create_level", "arguments": {"name": "L8", "elevation": 20}}]}))
    assert isinstance(drafted, list)


# ---- config flag -----------------------------------------------------------

def test_flag_off_removes_view_and_metadata(apps_off, server, gate):
    assert mcp_apps.PLAN_REVIEW_URI not in {str(r.uri) for r in mcp_resources.list_resources()}
    assert not [t for t in mcp_resources.list_resource_templates() if t.uriTemplate.startswith("ui://")]
    tools = asyncio.run(mcp_server.list_tools())
    assert all("ui" not in (t.meta or {}) for t in tools)
    with pytest.raises(mcp_apps.AppsResourceError):
        mcp_apps.read_resource(mcp_apps.PLAN_REVIEW_URI, gate)


def test_flag_defaults_to_auto(monkeypatch):
    from revit_mcp_server.config import Config

    monkeypatch.delenv("MCP_REVIT_MCP_APPS", raising=False)
    assert Config().mcp_apps == "auto"
    for raw, expected in (("always", "always"), ("OFF", "off"), ("auto", "auto"), ("false", "off"), ("true", "auto")):
        monkeypatch.setenv("MCP_REVIT_MCP_APPS", raw)
        assert Config().mcp_apps == expected, raw
    monkeypatch.setenv("MCP_REVIT_MCP_APPS", "sometimes")
    with pytest.raises(ValueError, match="auto, always or off"):
        Config()


# ---- per-plan resource: redaction and expiry -------------------------------

def _embedded(gate, plan_id):
    html, _ = mcp_apps.read_resource(f"ui://aec-model-bridge/plan-review/{plan_id}", gate)
    return html, json.loads(_scripts(html)[0][1])


def _mail_plan(gate):
    return gate.create_plan(
        [{"tool": "revit_set_parameter_value", "arguments": {"element_id": 7, "parameter_name": "Mark", "value": "B"}}],
        [{"7": {"Mark": "A"}}], review={"summary": "Requested by jane.doe@example.com"})


def test_per_plan_view_masks_personal_data_when_redaction_is_on(apps_on, gate, monkeypatch):
    monkeypatch.setenv("MCP_REVIT_REDACT_RESPONSES", "basic")
    plan = _mail_plan(gate)
    html, data = _embedded(gate, plan["plan_id"])
    assert "jane.doe@example.com" not in html and "example.com" not in html
    assert data["plans"][0]["review"]["summary"] == "Requested by <redacted-user>"


def test_per_plan_view_keeps_personal_data_when_redaction_is_off(apps_on, gate, monkeypatch):
    monkeypatch.setenv("MCP_REVIT_REDACT_RESPONSES", "off")
    plan = _mail_plan(gate)
    _, data = _embedded(gate, plan["plan_id"])
    assert data["plans"][0]["review"]["summary"] == "Requested by jane.doe@example.com"


# Runs the view script against a minimal DOM in node and prints the page text, one node per line.
_VIEW_HARNESS = r"""
const fs = require('fs');
const code = fs.readFileSync(process.argv[2], 'utf8');
const data = fs.readFileSync(process.argv[3], 'utf8');
function node(tag) {
  return { tag, children: [], className: '', _t: '', type: '',
    appendChild(c) { this.children.push(c); return c; },
    removeChild(c) { this.children = this.children.filter((x) => x !== c); },
    get firstChild() { return this.children[0] || null; },
    addEventListener() {},
    set textContent(v) { this._t = String(v); }, get textContent() { return this._t; } };
}
const root = node('main');
const embedded = node('script'); embedded.textContent = data;
global.document = { getElementById: (id) => (id === 'root' ? root : id === 'plan-data' ? embedded : null),
                    createElement: node, documentElement: {}, body: {} };
global.window = { addEventListener() {} }; window.parent = window;
global.navigator = {};
eval(code);
const out = [];
(function walk(n) { if (n._t) out.push(n._t); n.children.forEach(walk); })(root);
process.stdout.write(out.join('\n'));
"""


def _page_text(html, tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    data = json.loads(_scripts(html)[0][1])
    files = {"code.js": mcp_apps._SCRIPT, "data.json": json.dumps(data), "harness.js": _VIEW_HARNESS}
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    run = subprocess.run([node, str(tmp_path / "harness.js"), str(tmp_path / "code.js"), str(tmp_path / "data.json")],
                         capture_output=True, text=True, timeout=30, check=True)
    return run.stdout


def test_expired_pending_plan_shows_expired_without_approval_instructions(apps_on, tmp_path):
    gate = ApprovalGate(workspace_dir=tmp_path / "ws", approval_mode="ask_first", pending_ttl=3600)
    plan = _mail_plan(gate)
    stored = gate.load_plan(plan["plan_id"])
    stored["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    gate.save_plan(stored)
    html, data = _embedded(gate, plan["plan_id"])
    shown = data["plans"][0]
    assert shown["state"] == "expired" and shown["expired"] is True
    assert shown["expiry_reason"] == gate.expiry_reason(gate.load_plan(plan["plan_id"]))
    assert gate.load_plan(plan["plan_id"])["state"] == "pending"  # reading the view changes nothing
    text = _page_text(html, tmp_path)
    assert "expired" in text and "cannot be approved" in text
    assert "aec-model-bridge-approve approve" not in text and "Approve in the Revit panel" not in text


def test_live_pending_plan_keeps_approval_instructions(apps_on, tmp_path):
    gate = ApprovalGate(workspace_dir=tmp_path / "ws", approval_mode="ask_first", pending_ttl=3600)
    plan = _mail_plan(gate)
    html, data = _embedded(gate, plan["plan_id"])
    assert data["plans"][0]["state"] == "pending" and "expired" not in data["plans"][0]
    text = _page_text(html, tmp_path)
    assert f"aec-model-bridge-approve approve {plan['plan_id']}" in text and "expired" not in text


# ---- client capability (auto mode) -----------------------------------------

UI_EXTENSION = {mcp_apps.EXTENSION_ID: {"mimeTypes": [mcp_apps.MIME]}}


class _ExtensionClient(ClientSession):
    """SDK in-memory client that declares capabilities.extensions (the SDK has no option for it)."""

    extensions: dict | None = None

    async def initialize(self):
        caps = {"extensions": self.extensions} if self.extensions is not None else {}
        result = await self.send_request(
            types.ClientRequest(types.InitializeRequest(params=types.InitializeRequestParams(
                protocolVersion=types.LATEST_PROTOCOL_VERSION,
                capabilities=types.ClientCapabilities(**caps),
                clientInfo=types.Implementation(name="test-client", version="1"),
            ))),
            types.InitializeResult,
        )
        await self.send_notification(types.ClientNotification(types.InitializedNotification()))
        return result


async def _session_view(extensions):
    """tools/list _meta.ui and plan result _meta as one connected client sees them."""
    client_class = type("Client", (_ExtensionClient,), {"extensions": extensions})
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(memory, "ClientSession", client_class)
        async with memory.create_connected_server_and_client_session(mcp_server.app) as client:
            listed = await client.list_tools()
            listing = await client.call_tool("list_pending_plans", {})
    ui = {t.name: (t.meta or {}).get("ui") for t in listed.tools}
    return ui, listing.meta


def test_auto_sends_meta_ui_only_to_a_client_that_declared_the_extension(server, monkeypatch):
    monkeypatch.setattr(config, "mcp_apps", "auto")
    _, approval = server
    ui, meta = asyncio.run(_session_view(UI_EXTENSION))
    assert ui["plan_actions"] == {"resourceUri": mcp_apps.PLAN_REVIEW_URI, "visibility": ["model"]}
    assert ui["execute_plan"] == {"visibility": ["model"]}
    assert meta == {mcp_apps.APPROVAL_MODE_META_KEY: approval.gate.approval_mode}
    # The next session (same server, same SDK tool cache) declared nothing: no _meta.ui at all.
    ui, meta = asyncio.run(_session_view(None))
    assert not [name for name, value in ui.items() if value is not None]
    assert not (meta or {}).get(mcp_apps.APPROVAL_MODE_META_KEY)
    # And a declaring session after that gets it again: nothing is cached across sessions.
    ui, _ = asyncio.run(_session_view(UI_EXTENSION))
    assert ui["list_pending_plans"]["resourceUri"] == mcp_apps.PLAN_REVIEW_URI


def test_auto_ignores_other_extensions_and_other_mime_types(server, monkeypatch):
    monkeypatch.setattr(config, "mcp_apps", "auto")
    for extensions in ({"io.example/other": {}}, {mcp_apps.EXTENSION_ID: {"mimeTypes": ["text/html"]}}):
        ui, _ = asyncio.run(_session_view(extensions))
        assert not [name for name, value in ui.items() if value is not None], extensions


def test_always_and_off_ignore_the_client(server, monkeypatch):
    monkeypatch.setattr(config, "mcp_apps", "always")
    ui, _ = asyncio.run(_session_view(None))
    assert ui["plan_actions"]["resourceUri"] == mcp_apps.PLAN_REVIEW_URI
    monkeypatch.setattr(config, "mcp_apps", "off")
    ui, meta = asyncio.run(_session_view(UI_EXTENSION))
    assert not [name for name, value in ui.items() if value is not None]
    assert meta is None


def test_auto_outside_a_request_sends_no_meta_ui(server, monkeypatch):
    monkeypatch.setattr(config, "mcp_apps", "auto")
    assert all("ui" not in (t.meta or {}) for t in asyncio.run(mcp_server.list_tools()))
    # The view resources stay listed and readable; only _meta.ui depends on the client.
    assert mcp_apps.PLAN_REVIEW_URI in {str(r.uri) for r in mcp_resources.list_resources()}


@pytest.mark.parametrize("caps, expected", [
    ({"extensions": UI_EXTENSION}, True),
    ({"extensions": {mcp_apps.EXTENSION_ID: {}}}, True),
    ({"extensions": {mcp_apps.EXTENSION_ID: {"mimeTypes": "text/html;profile=mcp-app"}}}, False),
    ({"extensions": {mcp_apps.EXTENSION_ID: "yes"}}, False),
    ({"extensions": ["io.modelcontextprotocol/ui"]}, False),
    ({"experimental": {mcp_apps.EXTENSION_ID: {}}}, False),
    ({}, False),
])
def test_client_declared(caps, expected):
    session = SimpleNamespace(client_params=SimpleNamespace(capabilities=types.ClientCapabilities(**caps)))
    assert mcp_apps.client_declared(session) is expected
    assert mcp_apps.client_declared(None) is False
