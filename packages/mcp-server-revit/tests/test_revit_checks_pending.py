"""Durable read-only audit requests keep their retrieval handle without resubmitting."""
from __future__ import annotations

from typing import Any

import pytest

from revit_mcp_server.check_contract import save_json
from revit_mcp_server.security.workspace import WorkspaceMonitor
from test_revit_checks import CANNED, FakeBridge, _load_module


@pytest.fixture
def mod(monkeypatch: pytest.MonkeyPatch) -> Any:
    module = _load_module()
    monkeypatch.setattr(module, "_server_in_mock_mode", lambda: False)
    return module


READ_CALLS = [
    ("check_joins", {"ids": [1]}),
    ("check_intersections", {"set_a": {"ids": [1]}}),
    ("check_orientation", {"ids": [1]}),
    ("warnings_delta", {}),
    ("audit_openings", {"ids": [1]}),
    ("audit_roofs", {"ids": [1]}),
    ("probe_family", {"ids": [1]}),
    ("system_report", {"ids": [1]}),
    ("check_naming_and_params", {"ids": [1]}),
    ("check_levels_grids", {}),
]


@pytest.mark.parametrize("method,args", READ_CALLS)
@pytest.mark.parametrize("message", [None, "The durable request is still running."])
def test_running_audit_preserves_request_before_parsing(
    mod: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
    method: str, args: dict, message: str | None,
) -> None:
    raw = {"status": "running", "request_id": "read-request-17"}
    if message is not None:
        raw["message"] = message
    bridge = FakeBridge(raw=raw)

    def unexpected_parse(_text: str) -> Any:
        pytest.fail("A running request has no completed output to parse")

    monkeypatch.setattr(mod, "parse_script_output", unexpected_parse)
    result = getattr(mod.RevitModule(), method)(
        **args, workspace=WorkspaceMonitor([tmp_path]), tool_executor=bridge,
    )

    assert result["tool"] == "revit_" + method
    assert result["status"] == "running" and result["request_id"] == "read-request-17"
    assert result["verified"] is False and result["changed_ids"] == []
    assert "ok" not in result and "kind" not in result
    assert "revit_get_result" in result["hint"] and "Do not resubmit" in result["hint"]
    if message is not None:
        assert result["message"] == message
    else:
        assert "revit_get_result" in result["message"]
    assert len(bridge.calls) == 1
    assert bridge.calls[0][0] == "revit_execute_python" and bridge.calls[0][1]["mode"] == "read"
    assert not list(tmp_path.iterdir()), "Pending warnings must not write an empty baseline"


@pytest.mark.parametrize("pending_index", range(9))
@pytest.mark.parametrize("completed_has_failure", [False, True])
def test_default_review_stops_at_pending_check_and_preserves_completed_findings(
    mod: Any, tmp_path: Any, pending_index: int, completed_has_failure: bool,
) -> None:
    workspace = WorkspaceMonitor([tmp_path])
    path, why = save_json(workspace, "warnings_baseline_before", {"warnings": []})
    assert path is not None and not why
    calls = []

    def bridge(name: str, args: dict) -> dict:
        calls.append((name, args))
        if len(calls) == pending_index + 1:
            return {"status": "running", "request_id": "aggregate-request-31"}
        output = CANNED if completed_has_failure else "META\tdoc_title\tVilla.rvt\nMETA\tdoc_guid\tabc-123\nSUMMARY\tclean\nCOUNT\tfail\t0"
        return {"success": True, "output": output}

    result = mod.RevitModule().review(
        ids=[1], baseline_id="before", workspace=workspace, tool_executor=bridge,
    )

    wanted = list(mod.REVIEW_CHECKS)
    assert len(calls) == pending_index + 1, "Later checks must not be queued while Revit is busy"
    assert all(name == "revit_execute_python" and args["mode"] == "read" for name, args in calls)
    assert result["status"] == "running" and result["request_id"] == "aggregate-request-31"
    assert result["verified"] is False and "ok" not in result
    assert result["pending_check"] == wanted[pending_index]
    assert result["remaining_checks"] == wanted[pending_index + 1:]
    assert "revit_get_result" in result["hint"]
    if result["remaining_checks"]:
        assert "checks=remaining_checks" in result["hint"]
    else:
        assert "No further checks remain" in result["hint"]
    assert "Do not resubmit" in result["hint"]
    expected_fails = pending_index if completed_has_failure else 0
    assert result["fails_total"] == expected_fails
    assert len(result["fails"]) == expected_fails
    assert result["document"] == ({"title": "Villa.rvt", "guid": "abc-123"} if pending_index else {"title": "", "guid": ""})
    entries = result["checks"]
    assert [entry["check"] for entry in entries] == wanted
    assert all(entry["status"] == ("fail" if completed_has_failure else "pass") for entry in entries[:pending_index])
    assert entries[pending_index]["status"] == "running"
    assert entries[pending_index]["request_id"] == result["request_id"]
    assert all(entry["status"] == "not_verified" for entry in entries[pending_index + 1:])
    assert result["verdict"] == ("FAIL" if expected_fails else "INCOMPLETE")


def test_running_without_durable_handle_is_still_a_script_error(mod: Any) -> None:
    bridge = FakeBridge(raw={"status": "running"})
    result = mod.RevitModule().check_joins(ids=[1], tool_executor=bridge)
    assert result["kind"] == "script_error" and result["ok"] is False


@pytest.mark.parametrize("pending_again", [False, True])
def test_review_can_resume_only_its_unsubmitted_checks(mod: Any, tmp_path: Any, pending_again: bool) -> None:
    workspace = WorkspaceMonitor([tmp_path])
    first_bridge = FakeBridge(raw={"status": "running", "request_id": "levels-request"})
    first = mod.RevitModule().review(
        checks=["levels_grids", "joins", "orientation"], ids=[17], tag="P:phase1",
        workspace=workspace, tool_executor=first_bridge,
    )
    assert first["pending_check"] == "levels_grids"
    assert first["remaining_checks"] == ["joins", "orientation"]
    assert len(first_bridge.calls) == 1

    completed = "META\tdoc_title\tVilla.rvt\nMETA\tdoc_guid\tabc-123\nSUMMARY\tclean\nCOUNT\tfail\t0"
    second_bridge = FakeBridge(
        output=completed,
        raw={"status": "running", "request_id": "joins-request"} if pending_again else None,
    )
    resumed = mod.RevitModule().review(
        checks=first["remaining_checks"], ids=[17], tag="P:phase1",
        workspace=workspace, tool_executor=second_bridge,
    )
    assert [entry["check"] for entry in resumed["checks"]] == ["joins", "orientation"]
    for name, args in second_bridge.calls:
        assert name == "revit_execute_python" and args["mode"] == "read"
        assert "'ids': [17]" in args["script"] and "'tag': 'P:phase1'" in args["script"]
    if pending_again:
        assert len(second_bridge.calls) == 1
        assert resumed["pending_check"] == "joins" and resumed["request_id"] == "joins-request"
        assert resumed["remaining_checks"] == ["orientation"]
    else:
        assert len(second_bridge.calls) == 2
        assert resumed["verdict"] == "PASS"
        assert "request_id" not in resumed and "pending_check" not in resumed
