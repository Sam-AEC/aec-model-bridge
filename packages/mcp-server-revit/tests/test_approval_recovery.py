"""Stuck 'running' actions: explicit human-only recovery, at-most-once preserved,
and the bounded retry around os.replace."""
from __future__ import annotations

import asyncio
import io
import os
from datetime import datetime, timedelta, timezone

import pytest

from helpers import human_approve
from revit_mcp_server import approve_cli, mcp_server
from revit_mcp_server.errors import BridgeError
from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security import approval as approval_mod
from revit_mcp_server.security.approval import ApprovalGate, running_actions
from revit_mcp_server.security.workspace import WorkspaceMonitor

SET = "revit_set_parameter_value"


def _args(i):
    return {"element_id": i, "parameter_name": "FireRating", "value": "60"}


def _stuck_plan(tmp_path, age_minutes=60, n=2):
    """Approved plan with n actions; the first was claimed and its process 'crashed'."""
    gate = ApprovalGate(tmp_path, "required")
    plan = gate.create_plan([{"tool": SET, "arguments": _args(i)} for i in range(1, n + 1)],
                            [{} for _ in range(n)])
    pid = plan["plan_id"]
    human_approve(gate, pid)
    claim = gate.claim_action(SET, {**_args(1), "plan_id": pid})
    p = gate.load_plan(pid)
    p["actions"][0]["claimed_at"] = (datetime.now(timezone.utc) - timedelta(minutes=age_minutes)).isoformat()
    gate.save_plan(p)
    return gate, pid, claim


def test_running_actions_reports_age_and_stale(tmp_path):
    gate, pid, _ = _stuck_plan(tmp_path, age_minutes=60)
    (r,) = running_actions(gate.load_plan(pid))
    assert r["stale"] and 3500 < r["age_seconds"] < 3700


def test_recover_abandons_closes_plan_and_never_reruns(tmp_path):
    gate, pid, _ = _stuck_plan(tmp_path)
    plan = gate.recover_running_actions(pid, "Revit crashed", by="Sam")
    a1, a2 = plan["actions"]
    assert a1["state"] == "abandoned" and a1["abandoned_reason"] == "Revit crashed"
    assert a1["abandoned_by"] == "Sam" and a1["abandoned_at"]
    assert a2.get("state") in (None, "pending")
    assert plan["state"] == "partial"
    # at-most-once: neither the abandoned action nor the remaining one can be claimed
    for i in (1, 2):
        with pytest.raises(BridgeError):
            gate.claim_action(SET, {**_args(i), "plan_id": pid})
    # a late finish from the "dead" process does not revive the action
    gate.finish_action({"plan_id": pid, "action_id": a1["action_id"]}, ok=True)
    assert gate.load_plan(pid)["actions"][0]["state"] == "abandoned"
    assert gate.load_plan(pid)["state"] == "partial"


def test_recover_requires_reason_and_running_action(tmp_path):
    gate, pid, _ = _stuck_plan(tmp_path)
    with pytest.raises(BridgeError, match="reason"):
        gate.recover_running_actions(pid, "  ")
    gate.recover_running_actions(pid, "dead")
    with pytest.raises(BridgeError, match="nothing to recover"):
        gate.recover_running_actions(pid, "again")


def test_recent_running_action_needs_force(tmp_path):
    gate, pid, _ = _stuck_plan(tmp_path, age_minutes=0)
    with pytest.raises(BridgeError, match="may still be running"):
        gate.recover_running_actions(pid, "x")
    assert gate.load_plan(pid)["actions"][0]["state"] == "running"
    gate.recover_running_actions(pid, "x", force=True)
    assert gate.load_plan(pid)["actions"][0]["state"] == "abandoned"


def test_old_running_action_is_not_auto_recovered(tmp_path):
    gate, pid, _ = _stuck_plan(tmp_path, age_minutes=24 * 60)
    gate.load_plan(pid)
    gate.list_pending_plans()
    gate.claim_action(SET, {**_args(2), "plan_id": pid})
    assert gate.load_plan(pid)["actions"][0]["state"] == "running"


def test_recover_is_not_an_mcp_tool(tmp_path):
    registry, approval, job_manager, _m, _w = build_registry(WorkspaceMonitor([tmp_path]))
    previous = (mcp_server.registry, mcp_server.approval_provider, mcp_server.job_manager)
    mcp_server.registry, mcp_server.approval_provider, mcp_server.job_manager = registry, approval, job_manager
    try:
        listed = {t.name for t in asyncio.run(mcp_server.list_tools())}
        registered = {t.name for t in registry.get_all_tools()}
    finally:
        mcp_server.registry, mcp_server.approval_provider, mcp_server.job_manager = previous
    for name in listed | registered:
        assert "recover" not in name and "abandon" not in name


def test_cli_show_flags_stale_and_recover_round_trip(tmp_path, monkeypatch, capsys):
    gate, pid, _ = _stuck_plan(tmp_path)
    ws = ["--workspace", str(tmp_path)]
    assert approve_cli.main(ws + ["show", pid]) == 0
    out = capsys.readouterr().out
    assert "stuck in 'running'" in out and "STALE" in out
    # no terminal and no --yes: refused, plan unchanged
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert approve_cli.main(ws + ["recover", pid, "--reason", "crash"]) == 2
    assert gate.load_plan(pid)["actions"][0]["state"] == "running"
    assert approve_cli.main(ws + ["recover", pid, "--reason", "crash", "--yes"]) == 0
    plan = gate.load_plan(pid)
    assert plan["actions"][0]["state"] == "abandoned" and plan["state"] == "partial"
    assert approve_cli.main(ws + ["show", pid]) == 0
    assert "Abandoned:" in capsys.readouterr().out
    assert approve_cli.main(ws + ["recover", pid, "--reason", "again", "--yes"]) == 1


def test_cli_recover_needs_reason():
    with pytest.raises(SystemExit):
        approve_cli.main(["recover", "plan_000000000000"])


# ---- replace_with_retry -----------------------------------------------------------


def test_replace_retries_transient_permission_error(tmp_path, monkeypatch):
    src, dst = tmp_path / "a", tmp_path / "b"
    src.write_text("new")
    dst.write_text("old")
    real, calls = os.replace, {"n": 0}

    def flaky(s, d):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("locked")
        return real(s, d)

    monkeypatch.setattr(approval_mod.os, "replace", flaky)
    monkeypatch.setattr(approval_mod.time, "sleep", lambda s: None)
    approval_mod.replace_with_retry(src, dst)
    assert calls["n"] == 3 and dst.read_text() == "new"


def test_replace_gives_up_with_clear_error_and_leaves_target(tmp_path, monkeypatch):
    src, dst = tmp_path / "a", tmp_path / "b"
    src.write_text("new")
    dst.write_text("old")
    calls = {"n": 0}

    def locked(s, d):
        calls["n"] += 1
        raise PermissionError("locked")

    monkeypatch.setattr(approval_mod.os, "replace", locked)
    monkeypatch.setattr(approval_mod.time, "sleep", lambda s: None)
    with pytest.raises(BridgeError, match="locked by another program"):
        approval_mod.replace_with_retry(src, dst)
    assert calls["n"] == approval_mod.REPLACE_ATTEMPTS and dst.read_text() == "old"


def test_replace_does_not_retry_other_errors(tmp_path, monkeypatch):
    calls = {"n": 0}

    def boom(s, d):
        calls["n"] += 1
        raise FileNotFoundError("gone")

    monkeypatch.setattr(approval_mod.os, "replace", boom)
    with pytest.raises(FileNotFoundError):
        approval_mod.replace_with_retry(tmp_path / "a", tmp_path / "b")
    assert calls["n"] == 1


def test_save_plan_survives_transient_lock(tmp_path, monkeypatch):
    gate = ApprovalGate(tmp_path, "required")
    plan = gate.create_plan([{"tool": SET, "arguments": _args(1)}], [{}])
    real, calls = os.replace, {"n": 0}

    def flaky(s, d):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("locked")
        return real(s, d)

    monkeypatch.setattr(approval_mod.os, "replace", flaky)
    monkeypatch.setattr(approval_mod.time, "sleep", lambda s: None)
    gate.save_plan(plan)
    assert gate.load_plan(plan["plan_id"])["plan_id"] == plan["plan_id"]
