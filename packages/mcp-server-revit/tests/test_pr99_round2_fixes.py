"""PR #99 round-2 review fixes: workspace confinement of report writers, anchored ids,
plans only name registered tools, and the panel shows what a person approves."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from revit_mcp_server.errors import BridgeError, WorkspaceViolation
from revit_mcp_server.modules.report_generator.module import ReportGeneratorModule
from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security import proof
from revit_mcp_server.security.approval import ApprovalGate, validate_plan_id
from revit_mcp_server.security.workspace import WorkspaceMonitor

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "ws"
    (root / "plans").mkdir(parents=True)
    (root / "proofs").mkdir()
    return WorkspaceMonitor([root]), root


# ---- H3: report writers stay inside the workspace, out of plans/ and proofs/ ------


@pytest.mark.parametrize("method", ["export_excel", "export_sqlite_summary"])
@pytest.mark.parametrize("bad", ["../escape_out", "plans/plan_0123456789ab.json", "proofs/p.json",
                                 "plans/.claims/plan_0123456789ab.act_0123456789ab"])
def test_report_writers_refuse_escape_and_reserved_dirs(ws, method, bad):
    monitor, root = ws
    with pytest.raises((ValueError, WorkspaceViolation)):
        getattr(ReportGeneratorModule(), method)(output_filename=bad, workspace=monitor)
    assert not (root.parent / "escape_out").exists()
    assert list((root / "plans").rglob("*")) == []
    assert list((root / "proofs").rglob("*")) == []


def test_report_writers_refuse_absolute_path(ws, tmp_path):
    monitor, _root = ws
    outside = tmp_path / "outside.xlsx"
    with pytest.raises((ValueError, WorkspaceViolation)):
        ReportGeneratorModule().export_excel(output_filename=str(outside), workspace=monitor)
    assert not outside.exists()


def test_report_writers_still_write_in_workspace(ws):
    monitor, root = ws
    module = ReportGeneratorModule()
    assert Path(module.export_excel(output_filename="ok.xlsx", workspace=monitor)["output_file"]).exists()
    module.export_sqlite_summary(output_filename="ok.db", workspace=monitor)
    assert (root / "ok.db").exists()


def test_workspace_monitor_refuses_plans_and_proofs(ws):
    monitor, root = ws
    for sub in ("plans/plan_0123456789ab.json", "plans/.claims/x", "proofs/p.json"):
        with pytest.raises(WorkspaceViolation):
            monitor.assert_in_workspace(root / sub)
    ok = root / "reports" / "a.xlsx"
    assert monitor.assert_in_workspace(ok) == ok.resolve()


def test_exporter_cannot_precreate_a_claim_file(ws):
    monitor, root = ws
    registry, _approval, _jobs, _m, _w = build_registry(monitor)
    provider = registry.lookup_tool_provider("exporter_to_sqlite")
    claim = root / "plans" / ".claims" / "plan_0123456789ab.act_0123456789ab"
    with pytest.raises(ValueError):
        asyncio.run(provider.execute_tool("exporter_to_sqlite", {"db_path": str(claim), "elements": []}))
    assert not claim.exists()


# ---- L1: ids are fully matched, a trailing newline is refused ---------------------


@pytest.mark.parametrize("bad", ["plan_0123456789ab\n", "plan_0123456789ab ", "\nplan_0123456789ab"])
def test_plan_id_rejects_trailing_whitespace(bad):
    with pytest.raises(BridgeError):
        validate_plan_id(bad)


def test_plan_id_accepts_canonical():
    assert validate_plan_id("plan_0123456789ab") == "plan_0123456789ab"


def test_action_id_rejects_trailing_newline(tmp_path):
    gate = ApprovalGate(tmp_path)
    with pytest.raises(BridgeError):
        gate._claim_marker("plan_0123456789ab", "act_0123456789ab\n")


def test_proof_ids_reject_trailing_newline(tmp_path):
    with pytest.raises(Exception):
        proof.validate_plan_id("plan_0123456789ab\n")


# ---- H2: plans only name registered tools ----------------------------------------


def test_plan_actions_refuses_unregistered_tool(ws):
    monitor, _root = ws
    _registry, approval, _jobs, _m, _w = build_registry(monitor)
    with pytest.raises(BridgeError, match="not a registered tool"):
        asyncio.run(approval.execute_tool("plan_actions", {"actions": [
            {"tool": "revit_harmless_looking_name", "arguments": {"element_id": 1}}]}))
    assert approval.gate.list_pending_plans() == []


def test_plan_actions_accepts_registered_tool(ws):
    monitor, _root = ws
    _registry, approval, _jobs, _m, _w = build_registry(monitor)
    plan = asyncio.run(approval.execute_tool("plan_actions", {"actions": [
        {"tool": "revit_delete_element", "arguments": {"element_id": 1}}]}))
    assert plan["plan_id"].startswith("plan_")


# ---- H2: the panel shows each action's escaped arguments --------------------------

NODE = shutil.which("node")

HARNESS = r"""
const fs = require('fs');
// Windows checkouts convert app.js to CRLF (.gitattributes: text=auto); normalise so the
// function-boundary regex below sees "\n}\n" on every platform.
const src = fs.readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const grab = (n) => src.match(new RegExp('function ' + n + '\\([\\s\\S]*?\\n}\\n'))[0];
const consts = 'const state = { plansOmitted: 0 }; const REVIEW_LIST_CAP = 100, PLAN_LIMIT = 50, PLAN_ID_SHAPE = /^plan_[0-9a-f]{12}$/;\n';
const code = consts + ['escapeHtml', 'visibleText', 'stringifyForReview', 'planActionLines',
  'isPlainObject', 'reviewBlocked', 'planReviewState', 'mapPlans']
  .map(grab).join('\n') + '\nglobalThis.mapPlans = mapPlans; globalThis.escapeHtml = escapeHtml; globalThis.visibleText = visibleText;';
(0, eval)(code);
const plans = mapPlans({plans: [{plan_id: 'plan_0123456789ab', plan_hash: 'h', state: 'pending', actions: [
  {tool: 'revit_delete_element',
   arguments: {element_id: 42, note: '<img src=x onerror=1>‮\u001b[2J\u0007'},
   diff: {before: {value: '60'}}}]}]});
console.log(JSON.stringify({review: plans[0].review, html: escapeHtml(plans[0].review),
  visible: visibleText('a\nb\tc\u0007\u202e\u200b')}));
"""


def run_harness(tmp_path, app_js):
    script = tmp_path / "harness.js"
    script.write_text(HARNESS, encoding="utf-8")
    # The path travels as a process argument (never spliced into JS source) and the output is
    # decoded as UTF-8 explicitly: the harness prints U+202E, which a cp1252 default would mangle.
    proc = subprocess.run([NODE, str(script), str(app_js)], capture_output=True,
                          encoding="utf-8", errors="replace", check=False)
    assert proc.returncode == 0, (
        f"node harness exited {proc.returncode}\nstdout: {proc.stdout}\nstderr: {proc.stderr}")
    return json.loads(proc.stdout)


def assert_escaped_review(data):
    assert '"element_id": 42' in data["review"]
    assert '"value": "60"' in data["review"]
    assert "\u202e" not in data["review"] and "\x1b" not in data["review"]
    assert "\\u202e" in data["review"]
    # Pretty-printed JSON keeps its real line breaks (readable), while BEL stays visibly escaped.
    assert "{\n  \"element_id\": 42" in data["review"]
    assert "\\x0a" not in data["review"] and "\\x09" not in data["review"]
    assert "\x07" not in data["review"] and "\\u0007" in data["review"]
    # visibleText itself: \n and \t stay real whitespace; BEL and bidi/format chars are escaped.
    assert data["visible"] == "a\nb\tc\\x07\\u202e\\u200b"
    assert "<img" not in data["html"] and "&lt;img" in data["html"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_panel_plans_view_shows_escaped_arguments(tmp_path):
    assert_escaped_review(run_harness(tmp_path, REPO / "panel" / "app.js"))


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_panel_plans_view_survives_crlf_checkout(tmp_path):
    # Windows checkouts get CRLF line endings via .gitattributes (text=auto).
    src = (REPO / "panel" / "app.js").read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    crlf = tmp_path / "app crlf.js"
    crlf.write_bytes(src)
    assert_escaped_review(run_harness(tmp_path, crlf))
