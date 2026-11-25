"""Content binding of files a write tool reads at run time (security/file_binding.py).

revit_batch_create_sheets_from_csv reads its CSV when the approved plan runs. plan_actions records
the sha256 and row count of the CSV in the hashed action arguments, the review shows them, and the
run is refused before anything is sent to Revit when the file changed or is gone."""
from __future__ import annotations

import hashlib

import pytest

from revit_mcp_server.config import BridgeMode
from revit_mcp_server.errors import BridgeError
from revit_mcp_server.providers import revit_payloads
from revit_mcp_server.providers.approval_provider import ApprovalProvider
from revit_mcp_server.providers.registry import ProviderRegistry
from revit_mcp_server.providers.revit import RevitProvider
from revit_mcp_server.security import file_binding
from revit_mcp_server.security.approval import plan_hash
from revit_mcp_server.security.workspace import WorkspaceMonitor
from helpers import panel_decide

TOOL = "revit_batch_create_sheets_from_csv"
CSV = "sheet_number,sheet_name\nA101,Plan\nA102,Section\n"


@pytest.fixture
def setup(tmp_path):
    registry = ProviderRegistry()
    workspace = WorkspaceMonitor([tmp_path])
    approval = ApprovalProvider(workspace=workspace, registry=registry, approval_mode="required")
    registry.register(approval)
    revit = RevitProvider(workspace=workspace, mode=BridgeMode.mock)
    sent = []
    bridge, builder = revit._tool_mapping[TOOL]

    def recording(args):
        payload = builder(args)
        sent.append(payload)
        return payload

    revit._tool_mapping[TOOL] = (bridge, recording)
    registry.register(revit)
    path = tmp_path / "sheets.csv"
    path.write_text(CSV, encoding="utf-8", newline="")
    return approval, path, sent


async def _approved_plan(approval, path):
    plan = await approval.execute_tool("plan_actions", {
        "actions": [{"tool": TOOL, "arguments": {"csv_path": str(path), "titleblock_name": "A1"}}],
    })
    await panel_decide(approval, "approve_plan", plan["plan_id"])
    return plan


def test_csv_cap_matches_the_payload_builder():
    assert file_binding.CSV_MAX_BYTES == revit_payloads.CSV_MAX_BYTES


@pytest.mark.anyio
async def test_plan_records_digest_and_rows_in_hashed_arguments_and_preview(setup):
    approval, path, _ = setup
    plan = await approval.execute_tool("plan_actions", {
        "actions": [{"tool": TOOL, "arguments": {"csv_path": str(path)}}],
    })
    digest = "sha256:" + hashlib.sha256(CSV.encode("utf-8")).hexdigest()
    args = plan["actions"][0]["arguments"]
    assert args["csv_sha256"] == digest and args["csv_row_count"] == 2
    assert plan["actions"][0]["diff"]["after"]["csv_sha256"] == digest
    assert plan["bound_files"] == [{"action_id": plan["actions"][0]["action_id"], "tool": TOOL,
                                    "path": str(path), "sha256": digest, "rows": 2}]
    assert digest in plan["preview_markdown"] and "(2 rows)" in plan["preview_markdown"]
    # The digest is part of the plan hash: editing it on disk invalidates the plan.
    stored = approval.gate.load_plan(plan["plan_id"])
    stored["actions"][0]["arguments"]["csv_sha256"] = "sha256:" + "0" * 64
    assert plan_hash(stored) != stored["plan_hash"]
    listed = await approval.execute_tool("list_pending_plans", {})
    assert listed["plans"][0]["bound_files"][0]["sha256"] == digest


@pytest.mark.anyio
async def test_unchanged_csv_runs_and_sends_its_rows(setup):
    approval, path, sent = setup
    plan = await _approved_plan(approval, path)
    result = await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    assert result["ok"], result
    assert sent[-1]["sheets"][0] == {"sheet_number": "A101", "sheet_name": "Plan", "titleblock_name": "A1"}


@pytest.mark.anyio
async def test_changed_csv_is_refused_before_anything_is_sent(setup):
    approval, path, sent = setup
    plan = await _approved_plan(approval, path)
    path.write_text(CSV + "A103,Hidden extra\n", encoding="utf-8", newline="")
    with pytest.raises(BridgeError, match="changed after the plan was approved; draft a new plan"):
        await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    assert sent == []
    stored = approval.gate.load_plan(plan["plan_id"])
    assert stored["state"] == "approved" and stored["actions"][0]["state"] == "pending"  # nothing consumed


@pytest.mark.anyio
async def test_missing_csv_is_refused(setup):
    approval, path, sent = setup
    plan = await _approved_plan(approval, path)
    path.unlink()
    with pytest.raises(BridgeError, match="cannot be read now"):
        await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    assert sent == []


@pytest.mark.anyio
async def test_direct_call_with_plan_id_is_refused_when_csv_changed(setup):
    approval, path, sent = setup
    plan = await _approved_plan(approval, path)
    args = dict(plan["actions"][0]["arguments"], plan_id=plan["plan_id"])
    path.write_text("sheet_number,sheet_name\nX1,Other\n", encoding="utf-8", newline="")
    with pytest.raises(BridgeError, match="changed after the plan was approved"):
        approval.gate.claim_action(TOOL, args)
    assert sent == []


def test_builder_refuses_a_digest_that_does_not_match(setup, tmp_path):
    _approval, path, _ = setup
    revit = RevitProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.mock)
    _bridge, builder = revit._tool_mapping[TOOL]
    good = file_binding.digest(path.read_bytes())
    assert len(builder({"csv_path": str(path), "csv_sha256": good})["sheets"]) == 2
    with pytest.raises(BridgeError, match="changed after the plan was approved"):
        builder({"csv_path": str(path), "csv_sha256": "sha256:" + "f" * 64})


@pytest.mark.anyio
async def test_plan_refuses_missing_bad_or_forged_csv(setup, tmp_path):
    approval, path, _ = setup
    with pytest.raises(BridgeError, match="no CSV file"):
        await approval.execute_tool("plan_actions", {
            "actions": [{"tool": TOOL, "arguments": {"csv_path": str(tmp_path / "missing.csv")}}]})
    with pytest.raises(BridgeError, match="set by the server"):
        await approval.execute_tool("plan_actions", {
            "actions": [{"tool": TOOL, "arguments": {"csv_path": str(path), "csv_sha256": "sha256:" + "0" * 64}}]})
    bad = tmp_path / "bad.csv"
    bad.write_text("number_only\n1\n", encoding="utf-8", newline="")
    with pytest.raises(BridgeError, match="needs a column"):
        await approval.execute_tool("plan_actions", {"actions": [{"tool": TOOL, "arguments": {"csv_path": str(bad)}}]})
    with pytest.raises(BridgeError, match="outside the allowed workspace"):
        await approval.execute_tool("plan_actions", {"actions": [{"tool": TOOL, "arguments": {"csv_path": "/etc/hosts"}}]})


def test_execution_refuses_a_bound_action_without_a_digest(tmp_path):
    with pytest.raises(BridgeError, match="holds no digest"):
        file_binding.verify_action(TOOL, {"csv_path": str(tmp_path / "x.csv")}, WorkspaceMonitor([tmp_path]))


def test_registry_lets_other_tools_opt_in(tmp_path, monkeypatch):
    spec = file_binding.BoundFile(path_key="source_path", digest_key="source_sha256", max_bytes=10)
    monkeypatch.setitem(file_binding.CONTENT_BOUND_FILES, "some_file_tool", spec)
    src = tmp_path / "in.txt"
    src.write_bytes(b"hello")
    ws = WorkspaceMonitor([tmp_path])
    [action] = file_binding.bind_actions([{"tool": "some_file_tool", "arguments": {"source_path": str(src)}}], ws)
    assert action["arguments"]["source_sha256"] == file_binding.digest(b"hello")
    file_binding.verify_action("some_file_tool", action["arguments"], ws)
    src.write_bytes(b"x" * 11)
    with pytest.raises(BridgeError, match="larger than 10 bytes"):
        file_binding.verify_action("some_file_tool", action["arguments"], ws)
