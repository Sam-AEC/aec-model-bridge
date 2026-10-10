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
const src = fs.readFileSync(process.argv[2], 'utf8');
const grab = (n) => src.match(new RegExp('function ' + n + '\\([\\s\\S]*?\\n}\\n'))[0];
const code = ['escapeHtml', 'visibleText', 'stringifyForReview', 'planActionLines', 'mapPlans']
  .map(grab).join('\n') + '\nglobalThis.mapPlans = mapPlans; globalThis.escapeHtml = escapeHtml;';
(0, eval)(code);
const plans = mapPlans({plans: [{plan_id: 'plan_0123456789ab', plan_hash: 'h', state: 'pending', actions: [
  {tool: 'revit_delete_element',
   arguments: {element_id: 42, note: '<img src=x onerror=1>‮\u001b[2J'},
   diff: {before: {value: '60'}}}]}]});
console.log(JSON.stringify({review: plans[0].review, html: escapeHtml(plans[0].review)}));
"""


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_panel_plans_view_shows_escaped_arguments(tmp_path):
    script = tmp_path / "harness.js"
    script.write_text(HARNESS, encoding="utf-8")
    out = subprocess.run([NODE, str(script), str(REPO / "panel" / "app.js")],
                         capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    assert '"element_id": 42' in data["review"]
    assert '"value": "60"' in data["review"]
    assert "‮" not in data["review"] and "\x1b" not in data["review"]
    assert "\\u202e" in data["review"]
    assert "<img" not in data["html"] and "&lt;img" in data["html"]
