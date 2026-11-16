"""aec-model-bridge-approve reject --older-than / --all-pending: a person's bulk cleanup of pending plans."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from helpers import human_approve
from revit_mcp_server import approve_cli
from revit_mcp_server.security.approval import ApprovalGate

SET = "revit_set_parameter_value"


def _plan(gate, value):
    plan = gate.create_plan([{"tool": SET, "arguments": {"element_id": 1, "parameter_name": "C", "value": value}}], [{}])
    return plan["plan_id"]


def _age(gate, plan_id, days):
    # Aged last: created_at is part of the plan hash, so approving and running come first.
    stored = gate.load_plan(plan_id)
    stored["created_at"] = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    gate.save_plan(stored)


@pytest.fixture
def plans(tmp_path):
    gate = ApprovalGate(tmp_path, "ask_first")
    ids = {"old": _plan(gate, "a"), "new": _plan(gate, "b"), "approved": _plan(gate, "c")}
    human_approve(gate, ids["approved"])
    ids["executed"] = _plan(gate, "d")
    human_approve(gate, ids["executed"])
    gate.mark_action_executed(SET, {"element_id": 1, "parameter_name": "C", "value": "d", "plan_id": ids["executed"]})
    assert gate.load_plan(ids["executed"])["state"] == "executed"
    for key in ("old", "approved", "executed"):
        _age(gate, ids[key], 10)
    return gate, ids, ["--workspace", str(tmp_path)]


def _state(gate, pid):
    return gate.load_plan(pid)["state"]


def test_older_than_rejects_only_old_pending_plans(plans, capsys):
    gate, ids, ws = plans
    assert approve_cli.main(ws + ["reject", "--older-than", "7", "--yes"]) == 0
    out = capsys.readouterr().out
    assert ids["old"] in out and ids["new"] not in out
    assert _state(gate, ids["old"]) == "rejected" and _state(gate, ids["new"]) == "pending"
    assert _state(gate, ids["approved"]) == "approved" and _state(gate, ids["executed"]) == "executed"


def test_all_pending_leaves_approved_and_executed_alone(plans, capsys):
    gate, ids, ws = plans
    assert approve_cli.main(ws + ["reject", "--all-pending", "--yes"]) == 0
    out = capsys.readouterr().out
    assert ids["old"] in out and ids["new"] in out
    assert _state(gate, ids["old"]) == _state(gate, ids["new"]) == "rejected"
    assert _state(gate, ids["approved"]) == "approved" and _state(gate, ids["executed"]) == "executed"


def test_dry_run_prints_ids_and_changes_nothing(plans, capsys):
    gate, ids, ws = plans
    assert approve_cli.main(ws + ["reject", "--all-pending", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert ids["old"] in out and ids["new"] in out
    assert _state(gate, ids["old"]) == _state(gate, ids["new"]) == "pending"


def test_bulk_reject_needs_a_terminal_or_yes(plans, capsys, monkeypatch):
    gate, ids, ws = plans
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert approve_cli.main(ws + ["reject", "--all-pending"]) == 2
    assert _state(gate, ids["old"]) == "pending"


def test_reject_arguments_are_exclusive(plans, capsys):
    _, ids, ws = plans
    for argv in (["reject"], ["reject", ids["old"], "--all-pending"], ["reject", "--all-pending", "--older-than", "3"]):
        with pytest.raises(SystemExit):
            approve_cli.main(ws + argv)
    # a single reject by id still works
    assert approve_cli.main(ws + ["reject", ids["old"], "--yes"]) == 0


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "-1"])
def test_older_than_must_be_finite_and_not_negative(plans, capsys, bad):
    _, ids, ws = plans
    with pytest.raises(SystemExit) as exc:
        approve_cli.main(ws + ["reject", f"--older-than={bad}", "--yes"])
    assert exc.value.code == 2
    assert "--older-than must be" in capsys.readouterr().err
    assert approve_cli.main(ws + ["reject", "--older-than", "7", "--dry-run"]) == 0
