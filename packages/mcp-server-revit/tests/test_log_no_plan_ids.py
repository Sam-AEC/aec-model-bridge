"""Error logs from the approval gate name no plan id or claim (CodeQL clear-text logging rule).

Plan ids are in the audit trail and proof bundles; log lines only say what failed."""

from __future__ import annotations

import logging

from revit_mcp_server.security.approval import ApprovalGate


def test_failed_plan_load_logs_no_plan_id(tmp_path, caplog):
    gate = ApprovalGate(workspace_dir=tmp_path / "ws")
    plan = gate.create_plan(
        [{"tool": "revit_set_parameter_value", "arguments": {"element_id": 1, "parameter_name": "Mark", "value": "A"}}],
        [{"1": {"Mark": None}}])
    path = next(gate.plans_dir.glob(f"{plan['plan_id']}*.json"))
    path.write_text("{not json", encoding="utf-8")
    with caplog.at_level(logging.ERROR):
        assert gate.load_plan(plan["plan_id"]) is None
    assert caplog.records, "the failure is still logged"
    assert all(plan["plan_id"] not in r.getMessage() for r in caplog.records)
