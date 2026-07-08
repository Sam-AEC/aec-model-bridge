"""Tests for Phase 10 — QA/QC Checker module (W7, W9)."""
import importlib.util
import pytest
from pathlib import Path
from revit_mcp_server.semantic.engine import generate_mock_snapshot


def _load_mod(relpath: str, name: str):
    p = Path(__file__).parent.parent / relpath
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_qaqc = _load_mod("src/revit_mcp_server/modules/qaqc_checker/module.py", "_qaqc_impl")
QaqcCheckerModule = _qaqc.QaqcCheckerModule


class MockWorkspace:
    def __init__(self, tmp_path: Path):
        self.allowed_directories = [tmp_path]


@pytest.fixture
def workspace(tmp_path):
    return MockWorkspace(tmp_path)


@pytest.fixture
def module():
    return QaqcCheckerModule()


@pytest.fixture
def snap_and_ws(tmp_path):
    ws = MockWorkspace(tmp_path)
    snap = generate_mock_snapshot()
    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap_path = snap_dir / f"{snap.snapshot_id}.json"
    with open(snap_path, "w", encoding="utf-8") as f:
        f.write(snap.model_dump_json(by_alias=True, indent=2))
    return snap, ws


# --- Rule listing ---

def test_list_rules_core(module):
    result = module.list_rules(rule_pack="core")
    assert result["rules_count"] >= 10
    rule_ids = {r["id"] for r in result["rules"]}
    assert "room_not_placed" in rule_ids
    assert "door_missing_mark" in rule_ids
    assert "room_missing_number" in rule_ids


# --- Run check ---

def test_run_check_mock_snapshot(module, workspace):
    result = module.run_check(workspace=workspace)
    assert "total_findings" in result
    assert result["rules_run"] >= 10
    assert "by_severity" in result
    assert "error" in result["by_severity"]
    assert "warning" in result["by_severity"]
    assert "info" in result["by_severity"]
    # Check structure of findings
    for f in result["findings"]:
        assert "rule_id" in f
        assert "severity" in f
        assert "message" in f


def test_run_check_detects_unplaced_room(module, workspace):
    result = module.run_check(workspace=workspace)
    findings_by_rule = {f["rule_id"] for f in result["findings"]}
    # Mock snapshot has 1 unplaced room
    assert "room_not_placed" in findings_by_rule


def test_run_check_detects_missing_room_name(module, workspace):
    result = module.run_check(workspace=workspace)
    findings_by_rule = {f["rule_id"] for f in result["findings"]}
    # Mock snapshot rooms have no Name parameter → room_missing_name fires
    assert "room_missing_name" in findings_by_rule


def test_run_check_with_snapshot(module, snap_and_ws):
    snap, ws = snap_and_ws
    result = module.run_check(snapshot_id=snap.snapshot_id, workspace=ws)
    assert result["total_findings"] >= 1


# --- Issue store ---

def test_issues_persist_after_run(module, workspace):
    module.run_check(workspace=workspace)
    issues = module.list_issues(workspace=workspace)
    assert issues["total"] >= 1
    assert all("rule_id" in i for i in issues["issues"])
    assert all("status" in i for i in issues["issues"])
    assert all(i["status"] == "open" for i in issues["issues"])


def test_filter_issues_by_severity(module, workspace):
    module.run_check(workspace=workspace)
    errors = module.list_issues(severity="error", workspace=workspace)
    warnings = module.list_issues(severity="warning", workspace=workspace)
    assert all(i["severity"] == "error" for i in errors["issues"])
    assert all(i["severity"] == "warning" for i in warnings["issues"])


def test_resolve_issue(module, workspace):
    module.run_check(workspace=workspace)
    all_issues = module.list_issues(workspace=workspace)
    
    if not all_issues["issues"]:
        pytest.skip("No issues generated from mock snapshot")
    
    issue_id = all_issues["issues"][0]["id"]
    res = module.resolve_issue(issue_id=issue_id, workspace=workspace)
    assert res["status"] == "resolved"
    
    # Verify
    resolved = module.list_issues(status="resolved", workspace=workspace)
    assert any(i["id"] == issue_id for i in resolved["issues"])


def test_second_run_resolves_fixed_issues(module, workspace):
    """Running check twice with the same snapshot should keep issues open (not resolve them)."""
    module.run_check(workspace=workspace)
    first_count = module.list_issues(status="open", workspace=workspace)["total"]
    
    module.run_check(workspace=workspace)
    second_count = module.list_issues(status="open", workspace=workspace)["total"]
    
    # Same defects → same open count
    assert first_count == second_count


def test_resolve_nonexistent_issue_raises(module, workspace):
    # Ensure DB exists first
    module.run_check(workspace=workspace)
    with pytest.raises(ValueError, match="not found"):
        module.resolve_issue(issue_id="does-not-exist", workspace=workspace)
