"""Rolled-back preview of a plan (#293): revit.preview_plan_batch.

plan_actions asks the add-in to run the draft's actions in a TransactionGroup that is always rolled back and
stores what came back on the plan as ``rollback_preview``. The record is covered by the plan hash and shown by
the approval CLI and the panel. A preview is not an approval and not an execution.

The fake add-in below plays the add-in's part against a dict of parameter values. UNVERIFIED in live Revit:
the real rollback, the changed-element ids from DocumentChanged and the warnings are not observed here. The
add-in's request parsing has C# tests in packages/revit-bridge-addin-tests/PlanBatchTests.cs.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Dict, List

import pytest

from helpers import human_approve, panel_decide
from revit_mcp_server import approve_review
from revit_mcp_server.bridge import contract_generated as contract
from revit_mcp_server.bridge.client import PLAN_PREVIEW_COMMAND, BridgeClient
from revit_mcp_server.config import BridgeMode
from revit_mcp_server.errors import BridgeError
from revit_mcp_server.providers.approval_provider import ApprovalProvider
from revit_mcp_server.providers.registry import ProviderRegistry
from revit_mcp_server.providers.revit import PLAN_BATCH_COMMANDS, RevitProvider
from revit_mcp_server.security import proof as proof_mod
from revit_mcp_server.security import rollback_preview as rp
from revit_mcp_server.security.approval import ApprovalGate, plan_hash
from revit_mcp_server.security.workspace import WorkspaceMonitor

ROOT = Path(__file__).resolve().parents[3]
BRIDGE_SRC = ROOT / "packages" / "revit-bridge-addin" / "src" / "Bridge"


class PreviewAddin:
    """Parameter values plus the add-in's preview semantics: run every member, report each, then restore."""

    def __init__(self, supports: bool = True) -> None:
        self.values: Dict[int, Dict[str, Any]] = {1: {"Mark": "A"}, 2: {"Mark": "B"}}
        self.supports = supports
        self.previews: List[Dict[str, Any]] = []
        self.batches: List[Any] = []
        self.writes: List[tuple] = []
        self.fail_element: int | None = None
        self.reply: Any = None
        self.raises: BaseException | None = None
        self.values_during_preview: Dict[int, Dict[str, Any]] | None = None

    def send_tool(self, name: str, payload: dict) -> dict:
        if name == "revit.get_parameter_value":
            return {"value": self.values.get(payload["element_id"], {}).get(payload["parameter_name"]),
                    "storage_type": "String"}
        self.writes.append((name, payload))
        return {"status": "success"}

    def supports_plan_batch(self) -> bool:
        return True

    def call_plan_batch(self, *args: Any) -> dict:  # a preview must never reach the real batch
        self.batches.append(args)
        raise AssertionError("a preview must not use revit.execute_plan_batch")

    def supports_plan_preview(self) -> bool:
        return self.supports

    def call_plan_preview(self, title: str, actions: list) -> dict:
        self.previews.append({"title": title, "actions": actions})
        if self.raises is not None:
            raise self.raises
        if self.reply is not None:
            return self.reply
        saved = copy.deepcopy(self.values)
        results: List[Dict[str, Any]] = []
        failed = -1
        for i, action in enumerate(actions):
            p = action["payload"]
            if failed >= 0:
                results.append({"index": i, "action_id": action["action_id"], "tool": action["tool"], "ok": False,
                                "not_run": True, "error": "Not run"})
                continue
            if p["element_id"] == self.fail_element:
                failed = i
                results.append({"index": i, "action_id": action["action_id"], "tool": action["tool"], "ok": False,
                                "error": "Parameter 'Mark' is read-only"})
                continue
            self.values.setdefault(p["element_id"], {})[p["parameter_name"]] = p["value"]
            results.append({"index": i, "action_id": action["action_id"], "tool": action["tool"], "ok": True,
                            "result": {"element_id": p["element_id"], "new_value": p["value"], "status": "success",
                                       "warnings": [{"Severity": "Warning", "Message": "Duplicate Mark value.",
                                                     "ElementIds": [p["element_id"]]}]}})
        self.values_during_preview = copy.deepcopy(self.values)
        self.values = saved  # the group rollback
        return {"plan_preview": True, "committed": False, "rolled_back": True, "failed_index": failed,
                "failure": "Parameter 'Mark' is read-only" if failed >= 0 else None,
                "changed_element_ids": {"added": [], "modified": [a["payload"]["element_id"] for a in actions],
                                        "deleted": []},
                "results": results}


def make(tmp_path, addin: PreviewAddin | None = None, mode: str = "required"):
    addin = addin or PreviewAddin()
    registry = ProviderRegistry()
    approval = ApprovalProvider(workspace=WorkspaceMonitor([tmp_path]), registry=registry, approval_mode=mode)
    registry.register(approval)
    revit = RevitProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.bridge,
                          bridge_url="http://127.0.0.1:1", bridge_factory=lambda *args: addin)
    registry.register(revit)
    return approval, addin


def mark(element_id: int, value: str) -> dict:
    return {"tool": "revit_set_parameter_value",
            "arguments": {"element_id": element_id, "parameter_name": "Mark", "value": value}}


# --------------------------------------------------------------------------- drafting


@pytest.mark.anyio
async def test_plan_carries_a_hashed_preview_with_ids_before_after_and_warnings(tmp_path):
    approval, addin = make(tmp_path)

    plan = await approval.execute_tool("plan_actions", {"actions": [mark(1, "X"), mark(2, "Y")]})

    preview = plan["rollback_preview"]
    assert preview["status"] == "ok" and preview["rolled_back"] is True
    assert preview["changed_element_ids"] == [1, 2]
    first = preview["actions"][0]
    assert (first["element_id"], first["parameter"], first["before"], first["after"]) == (1, "Mark", "A", "X")
    assert preview["warnings"][0]["message"] == "Duplicate Mark value."
    assert addin.values == {1: {"Mark": "A"}, 2: {"Mark": "B"}}, "the preview must leave the model as it was"
    assert addin.values_during_preview[1]["Mark"] == "X", "the fake did run the write before rolling back"
    assert "rollback_preview" in proof_mod.HASHED_PLAN_KEYS_V1
    assert "rollback_preview" not in proof_mod.unhashed_metadata_keys(approval.gate.load_plan(plan["plan_id"]))
    request = addin.previews[0]
    assert [m["action_id"] for m in request["actions"]] == ["prev_0", "prev_1"]
    assert request["actions"][0]["tool"] == "revit.set_parameter_value"


@pytest.mark.anyio
async def test_a_preview_is_not_an_execution_or_an_approval(tmp_path):
    approval, addin = make(tmp_path)

    plan = await approval.execute_tool("plan_actions", {"actions": [mark(1, "X")]})
    stored = approval.gate.load_plan(plan["plan_id"])

    assert stored["state"] == "pending"
    assert all(a["state"] == "pending" for a in stored["actions"])
    assert not any(k in stored for k in ("approved_at", "approved_by", "executed_at", "results"))
    assert approval.gate.load_proof(plan["plan_id"]) is None
    assert addin.batches == [] and addin.writes == []
    with pytest.raises(ValueError, match="not 'approved'"):
        await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    assert addin.batches == [] and addin.writes == []


@pytest.mark.anyio
async def test_changing_the_preview_after_approval_refuses_execution(tmp_path):
    approval, addin = make(tmp_path)
    plan = await approval.execute_tool("plan_actions", {"actions": [mark(1, "X")]})
    await panel_decide(approval, "approve_plan", plan["plan_id"])

    stored = approval.gate.load_plan(plan["plan_id"])
    stored["rollback_preview"]["warnings"] = []
    approval.gate.save_plan(stored)

    with pytest.raises(BridgeError):
        await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    assert addin.batches == [] and addin.writes == []

    stored = approval.gate.load_plan(plan["plan_id"])
    del stored["rollback_preview"]
    approval.gate.save_plan(stored)
    with pytest.raises(BridgeError):
        await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})


@pytest.mark.anyio
async def test_a_changed_model_needs_a_new_preview_and_a_new_hash(tmp_path):
    approval, addin = make(tmp_path)
    first = await approval.execute_tool("plan_actions", {"actions": [mark(1, "X")]})
    addin.values[1]["Mark"] = "changed by someone else"
    second = await approval.execute_tool("plan_actions", {"actions": [mark(1, "X")]})

    assert second["rollback_preview"]["actions"][0]["before"] == "changed by someone else"
    assert first["rollback_preview"] != second["rollback_preview"]
    assert first["plan_hash"] != second["plan_hash"]
    # Approving the second plan with the first plan's hash is refused.
    with pytest.raises(ValueError, match="not the plan that was shown"):
        approval.gate.update_plan_state(second["plan_id"], "approved", via="panel", expected_hash=first["plan_hash"])


@pytest.mark.anyio
async def test_a_failed_step_is_recorded_and_the_model_is_untouched(tmp_path):
    addin = PreviewAddin()
    addin.fail_element = 2
    approval, _ = make(tmp_path, addin)

    plan = await approval.execute_tool("plan_actions", {"actions": [mark(1, "X"), mark(2, "Y"), mark(1, "Z")]})

    preview = plan["rollback_preview"]
    assert preview["status"] == "failed" and "read-only" in preview["reason"]
    assert [a["ok"] for a in preview["actions"]] == [True, False, False]
    assert addin.values == {1: {"Mark": "A"}, 2: {"Mark": "B"}}


@pytest.mark.anyio
async def test_an_exception_in_the_add_in_still_drafts_the_plan_without_a_preview_result(tmp_path):
    addin = PreviewAddin()
    addin.raises = BridgeError("Revit is busy")
    approval, _ = make(tmp_path, addin)

    plan = await approval.execute_tool("plan_actions", {"actions": [mark(1, "X")]})

    preview = plan["rollback_preview"]
    assert preview["status"] == "unavailable" and preview["rolled_back"] is True
    assert "BridgeError" in preview["reason"] and "Nothing was changed" in preview["reason"]
    assert preview["actions"] == [] and preview["changed_element_ids"] == []
    assert approval.gate.load_plan(plan["plan_id"])["state"] == "pending"


@pytest.mark.anyio
async def test_a_slow_revit_gives_an_unavailable_preview(tmp_path):
    addin = PreviewAddin()
    addin.reply = {"status": "running", "request_id": "r1"}
    approval, _ = make(tmp_path, addin)
    plan = await approval.execute_tool("plan_actions", {"actions": [mark(1, "X")]})
    assert plan["rollback_preview"]["status"] == "unavailable"
    assert "did not finish" in plan["rollback_preview"]["reason"]


@pytest.mark.anyio
async def test_a_preview_that_reports_it_committed_is_flagged_and_blocks_approval_in_the_review(tmp_path):
    addin = PreviewAddin()
    addin.reply = {"committed": True, "results": [{"index": 0, "ok": True, "result": {"new_value": "X"}}]}
    approval, _ = make(tmp_path, addin)
    plan = await approval.execute_tool("plan_actions", {"actions": [mark(1, "X")]})

    record = plan["rollback_preview"]
    assert record["rolled_back"] is False and "COMMITTED" in record["reason"]
    stored = approval.gate.load_plan(plan["plan_id"])
    review = approve_review.build_review(stored, approval.gate, stored["plan_hash"])
    assert review["approvable"] is False
    assert any("not rolled back" in r for r in review["not_approvable_reasons"])
    text = approve_review.render_review(review)
    assert "PREVIEW WAS NOT ROLLED BACK" in text


@pytest.mark.anyio
async def test_a_reply_that_does_not_match_the_plan_gives_an_unavailable_preview(tmp_path):
    addin = PreviewAddin()
    addin.reply = {"committed": False, "rolled_back": True, "results": []}
    approval, _ = make(tmp_path, addin)
    plan = await approval.execute_tool("plan_actions", {"actions": [mark(1, "X")]})
    assert plan["rollback_preview"]["status"] == "unavailable"
    assert "does not match" in plan["rollback_preview"]["reason"]


@pytest.mark.anyio
@pytest.mark.parametrize("case", ["no_support", "mock", "other_tool", "look_only"])
async def test_no_preview_is_taken_when_it_cannot_be(tmp_path, case):
    addin = PreviewAddin(supports=case != "no_support")
    approval, _ = make(tmp_path, addin, mode="look_only" if case == "look_only" else "required")
    actions = [mark(1, "X")]
    if case == "other_tool":
        actions = [{"tool": "revit_create_wall", "arguments": {"start": {"x": 0, "y": 0}, "end": {"x": 1, "y": 0},
                                                                "level_id": 1}}]
    if case == "mock":
        registry = ProviderRegistry()
        approval = ApprovalProvider(workspace=WorkspaceMonitor([tmp_path]), registry=registry, approval_mode="required")
        registry.register(approval)
        registry.register(RevitProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.mock))
    if case == "look_only":
        actions = [mark(1, "X")]
        # look_only refuses writes, but drafting is still allowed: the plan just carries no preview.
    plan = await approval.execute_tool("plan_actions", {"actions": actions})
    assert "rollback_preview" not in plan
    assert addin.previews == []


# --------------------------------------------------------------------------- record and hash


def test_create_plan_hashes_the_preview_and_refuses_a_malformed_one(tmp_path):
    gate = ApprovalGate(tmp_path, "required")
    record = rp.unavailable("no add-in")
    plain = gate.create_plan([mark(1, "X")], [{}])
    with_preview = gate.create_plan([mark(1, "X")], [{}], rollback_preview=record)
    assert with_preview["rollback_preview"] == record
    assert plan_hash(with_preview) == with_preview["plan_hash"]
    changed = {**with_preview, "rollback_preview": {**record, "reason": "other"}}
    assert plan_hash(changed) != with_preview["plan_hash"]
    without = {k: v for k, v in with_preview.items() if k != "rollback_preview"}
    assert plan_hash(without) != with_preview["plan_hash"], "a preview cannot be stripped after approval"
    assert "rollback_preview" not in plain
    with pytest.raises(BridgeError, match="Invalid rollback preview"):
        gate.create_plan([mark(1, "X")], [{}], rollback_preview={"version": 1})
    with pytest.raises(BridgeError, match="rollback_preview"):
        gate.create_plan([mark(1, "X")], [{}], extra={"rollback_preview": record})


def test_plans_without_a_preview_hash_as_before():
    plan = {"plan_id": "plan_1", "created_at": "t", "actions": [{"action_id": "act_1", "tool": "t", "arguments": {},
                                                                 "diff": {"before": {}}}]}
    assert proof_mod.plan_content_hash(plan).startswith("sha256:")
    assert proof_mod.plan_content_hash({**plan, "rollback_preview": rp.unavailable("x")}) != \
        proof_mod.plan_content_hash(plan)


@pytest.mark.parametrize("bad", [
    None, [], {"version": 2}, {"version": 1, "status": "maybe"},
    {"version": 1, "status": "ok", "rolled_back": "yes", "changed_element_ids": [], "actions": [], "warnings": []},
    {"version": 1, "status": "ok", "rolled_back": True, "changed_element_ids": ["1"], "actions": [], "warnings": []},
    {"version": 1, "status": "ok", "rolled_back": True, "changed_element_ids": [], "actions": [{"x": 1}], "warnings": []},
    {"version": 1, "status": "ok", "rolled_back": True, "changed_element_ids": [], "actions": [], "warnings": [],
     "extra": 1},
    {"version": 1, "status": "ok", "rolled_back": True, "changed_element_ids": [], "actions": [],
     "warnings": [{"message": 1}]},
])
def test_validate_is_strict(bad):
    with pytest.raises(ValueError):
        rp.validate(bad)


def test_build_caps_what_it_stores_and_never_invents_values():
    actions = [{"tool": "revit_set_parameter_value", "arguments": {"element_id": 1, "parameter_name": "Mark", "value": "x"}}]
    reply = {"committed": False, "rolled_back": True,
             "changed_element_ids": {"modified": list(range(1000))},
             "results": [{"index": 0, "ok": True, "result": {"warnings": [{"Message": "w" * 5000}] * 300}}]}
    record = rp.build(reply, actions, [{}])
    assert len(record["changed_element_ids"]) == rp.MAX_IDS
    assert len(record["warnings"]) == rp.MAX_WARNINGS
    assert len(record["warnings"][0]["message"]) <= rp.TEXT_LIMIT
    assert "before" not in record["actions"][0] and "after" not in record["actions"][0]
    assert rp.validate(record) is record


def test_markdown_lists_ids_values_and_warnings():
    actions = [mark(1, "X")]
    reply = {"committed": False, "rolled_back": True, "changed_element_ids": [1],
             "results": [{"index": 0, "ok": True, "result": {"new_value": "X", "warnings": ["Overlap"]}}]}
    text = "\n".join(rp.markdown(rp.build(reply, actions, [{"1": {"Mark": "A"}}])))
    assert "nothing was kept in the model" in text and "Changed element ids: 1." in text
    assert "before A -> after X" in text and "Overlap" in text
    assert "not valid" in "\n".join(rp.markdown({"version": 9}))


# --------------------------------------------------------------------------- review output


@pytest.mark.anyio
async def test_approve_show_and_list_pending_carry_the_preview(tmp_path):
    approval, _ = make(tmp_path)
    plan = await approval.execute_tool("plan_actions", {"actions": [mark(1, "X")]})
    stored = approval.gate.load_plan(plan["plan_id"])

    review = approve_review.build_review(stored, approval.gate, stored["plan_hash"])
    text = approve_review.render_review(review, width=100)
    assert review["rollback_preview"]["status"] == "ok" and review["approvable"] is True
    assert "Rolled-back preview (nothing was kept in the model)" in text
    assert "before A -> after X" in text and "Duplicate Mark value." in text

    pending = await approval.execute_tool("list_pending_plans", {})
    assert pending["plans"][0]["rollback_preview"] == stored["rollback_preview"]
    # A preview is shown only; approval still needs a person and the hash of what they were shown.
    human_approve(approval.gate, plan["plan_id"])
    assert approval.gate.load_plan(plan["plan_id"])["state"] == "approved"


# --------------------------------------------------------------------------- client and contract


class Http:
    def __init__(self) -> None:
        self.requests: List[Any] = []


def test_client_sends_one_preview_request_and_supports_it_only_when_listed(monkeypatch):
    client = BridgeClient("http://127.0.0.1:1", validate_payloads=True)
    client._tool_catalog = {PLAN_PREVIEW_COMMAND}
    assert client.supports_plan_preview() is True
    client._tool_catalog = {"revit.execute_plan_batch"}
    assert client.supports_plan_preview() is False
    client._tool_catalog = None
    assert client.supports_plan_preview() is False

    sent: List[Any] = []

    def fake_call_tool(tool, payload, wait_s=None):
        sent.append((tool, payload))
        return {"committed": False, "rolled_back": True, "results": []}

    monkeypatch.setattr(client, "call_tool", fake_call_tool)
    members = [{"action_id": "prev_0", "tool": "revit.move_element", "payload": {"element_id": 1}}]
    assert client.call_plan_preview("Preview", members)["rolled_back"] is True
    assert sent == [(PLAN_PREVIEW_COMMAND, {"plan_id": "preview", "title": "Preview", "actions": members})]
    with pytest.raises(ValueError):
        client.call_plan_preview("t", [])
    with pytest.raises(ValueError):
        client.call_plan_preview("t", members * 51)


def test_preview_command_has_the_same_contract_as_the_batch():
    schema = contract.COMMANDS[PLAN_PREVIEW_COMMAND]
    assert schema["is_mutating"] is True, "a preview runs writes, so it is flagged as a write command"
    assert schema["params"] == contract.COMMANDS["revit.execute_plan_batch"]["params"]
    item = schema["params"]["properties"]["actions"]["items"]
    assert set(item["properties"]["tool"]["enum"]) == set(PLAN_BATCH_COMMANDS)


def test_addin_preview_command_always_rolls_back_and_never_commits():
    source = (BRIDGE_SRC / "PlanPreviewCommand.cs").read_text(encoding="utf-8")
    assert re.search(r'\[BridgeCommand\("revit\.preview_plan_batch", IsMutating = true\)\]', source)
    body = source[source.index("private static object PreviewPlanBatch("):]
    assert "Assimilate" not in source and ".Commit(" not in source, "a preview must never keep the group"
    assert body.index("PlanBatch.Parse(payload, IsRegisteredCommand") < body.index("new TransactionGroup(")
    assert body.index("new TransactionGroup(") < body.index("Execute(app, action.Tool, action.Payload)")
    assert body.index("SafeRollBack(group)") < body.index("finally")
    finally_block = body[body.index("finally"):]
    assert "SafeRollBack(group)" in finally_block, "an exception must still end in a rollback"
    assert "committed = false" in body and "rolled_back = rolledBack" in body
    assert "DocumentChanged -= onChanged" in finally_block
    assert "doc.IsModifiable" in body


def test_addin_preview_uses_the_same_allowlist_as_the_batch():
    source = (BRIDGE_SRC / "PlanBatch.cs").read_text(encoding="utf-8")
    assert "string commandName = CommandName" in source
    command = (BRIDGE_SRC / "PlanPreviewCommand.cs").read_text(encoding="utf-8")
    assert '"revit.preview_plan_batch"' in command and "IsBatchable" in command
