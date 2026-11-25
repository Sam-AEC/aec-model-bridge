"""MCP Apps plan review view (ui://aec-model-bridge/plan-review): read-only, escaped, never an approval path."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from pathlib import Path

import pytest

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
    monkeypatch.setattr(config, "mcp_apps", True)


@pytest.fixture
def apps_off(monkeypatch):
    monkeypatch.setattr(config, "mcp_apps", False)


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


def _scripts(html):
    return re.findall(r"<script([^>]*)>(.*?)</script>", html, flags=re.S)


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
    assert 'type="application/json"' in attrs
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
    # Exactly two script elements: the inert JSON data block and the view's own code.
    assert html.count("<script") == 2 and html.count("</script") == 2
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
        page = re.sub(r'<script type="application/json"[^>]*>.*?</script>', "", html, flags=re.S)
        assert not re.search(r"https?:|wss?:|//[a-z0-9]", page, flags=re.I)
        for banned in (" src=", " href=", "@import", "url(", "fetch(", "XMLHttpRequest", "WebSocket",
                       "<iframe", "<link", "<img", "<form"):
            assert banned not in page, banned


def test_csp_allows_only_the_inline_code_by_hash():
    html = mcp_apps.render_html(None)
    csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html).group(1)
    code = _scripts(html)[-1][1]
    style = re.search(r"<style>(.*?)</style>", html, flags=re.S).group(1)

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


def test_flag_defaults_on(monkeypatch):
    from revit_mcp_server.config import Config

    monkeypatch.delenv("MCP_REVIT_MCP_APPS", raising=False)
    assert Config().mcp_apps is True
    monkeypatch.setenv("MCP_REVIT_MCP_APPS", "false")
    assert Config().mcp_apps is False
