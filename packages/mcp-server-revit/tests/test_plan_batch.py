"""One-step undo for a whole plan (#294): revit.execute_plan_batch.

execute_plan sends every action of an approved plan to the add-in as one batch when the add-in lists
the command and every action is a plain model write (PLAN_BATCH_TOOLS). The add-in runs them in one
Revit turn inside one TransactionGroup and assimilates it into one undo step, or rolls the group back
at the first failure. Otherwise execute_plan runs one action at a time, as before. Approval
bookkeeping is the same either way: each action is claimed before anything runs and its outcome is
recorded from the add-in's per-action result.

The fake bridge below plays the add-in's part. UNVERIFIED in live Revit: the undo step and the
rollback are not observed here. The add-in's Revit-free parsing has C# tests in
packages/revit-bridge-addin-tests/PlanBatchTests.cs.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest

from helpers import panel_decide
from revit_mcp_server.bridge import contract_generated as contract
from revit_mcp_server.bridge.client import MAX_PLAN_BATCH_ACTIONS, PLAN_BATCH_COMMAND, BridgeClient
from revit_mcp_server.config import BridgeMode
from revit_mcp_server.errors import BridgeError, CommandFailed
from revit_mcp_server.providers.approval_provider import ApprovalProvider
from revit_mcp_server.providers.registry import ProviderRegistry
from revit_mcp_server.providers.revit import PLAN_BATCH_COMMANDS, PLAN_BATCH_TOOLS, RevitProvider
from revit_mcp_server.security.workspace import WorkspaceMonitor

ROOT = Path(__file__).resolve().parents[3]
BRIDGE_SRC = ROOT / "packages" / "revit-bridge-addin" / "src" / "Bridge"


class FakeAddin:
    """A model of parameter values plus the add-in's plan-batch semantics: run in order, stop at the
    first failure, restore every value (the group rollback) and report each action."""

    def __init__(self, supports: bool = True) -> None:
        self.values: Dict[int, Dict[str, Any]] = {1: {"Mark": "A"}, 2: {"Mark": "B"}, 3: {"Mark": "C"}}
        self.supports = supports
        self.fail_element: int | None = None
        self.batches: List[Dict[str, Any]] = []
        self.single: List[tuple] = []
        self.batch_reply: Any = None
        self.batch_raises: BaseException | None = None
        self.on_batch = None

    # read and one-by-one path
    def send_tool(self, name: str, payload: dict) -> dict:
        self.single.append((name, payload))
        if name == "revit.get_parameter_value":
            value = self.values.get(payload["element_id"], {}).get(payload["parameter_name"])
            return {"value": value, "storage_type": "String"}
        if name == "revit.set_parameter_value":
            if payload["element_id"] == self.fail_element:
                raise CommandFailed("Bridge error: Parameter 'Mark' is read-only")
            self.values.setdefault(payload["element_id"], {})[payload["parameter_name"]] = payload["value"]
            return {"element_id": payload["element_id"], "status": "success"}
        return {"status": "success", "echo": name}

    def supports_plan_batch(self) -> bool:
        return self.supports

    def call_plan_batch(self, plan_id: str, title: str, actions: list) -> dict:
        self.batches.append({"plan_id": plan_id, "title": title, "actions": actions})
        if self.on_batch is not None:
            self.on_batch()
        if self.batch_raises is not None:
            raise self.batch_raises
        if self.batch_reply is not None:
            return self.batch_reply
        saved = copy.deepcopy(self.values)
        results, failed = [], -1
        for i, action in enumerate(actions):
            payload = action["payload"]
            if action["tool"] == "revit.set_parameter_value" and payload["element_id"] == self.fail_element:
                failed = i
                results.append({"index": i, "action_id": action["action_id"], "tool": action["tool"], "ok": False,
                                "error": "Parameter 'Mark' is read-only"})
                break
            if action["tool"] == "revit.set_parameter_value":
                self.values.setdefault(payload["element_id"], {})[payload["parameter_name"]] = payload["value"]
            results.append({"index": i, "action_id": action["action_id"], "tool": action["tool"], "ok": True,
                            "result": {"status": "success"}})
        if failed >= 0:
            self.values = saved  # the group rollback
            for i in range(len(results)):
                if i < failed:
                    results[i] = {"index": i, "action_id": actions[i]["action_id"], "tool": actions[i]["tool"],
                                  "ok": False, "rolled_back": True, "error": "Rolled back"}
            for i in range(failed + 1, len(actions)):
                results.append({"index": i, "action_id": actions[i]["action_id"], "tool": actions[i]["tool"],
                                "ok": False, "not_run": True, "error": "Not run"})
        return {"plan_batch": True, "plan_id": plan_id, "committed": failed < 0,
                "group_name": f"AEC Model Bridge: {title} ({plan_id[5:13]})", "failed_index": failed,
                "results": results}


def make(tmp_path, addin: FakeAddin | None = None):
    addin = addin or FakeAddin()
    registry = ProviderRegistry()
    approval = ApprovalProvider(workspace=WorkspaceMonitor([tmp_path]), registry=registry, approval_mode="required")
    registry.register(approval)
    revit = RevitProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.bridge,
                          bridge_url="http://127.0.0.1:1", bridge_factory=lambda *args: addin)
    registry.register(revit)
    return approval, revit, addin


def mark(element_id: int, value: str) -> dict:
    return {"tool": "revit_set_parameter_value",
            "arguments": {"element_id": element_id, "parameter_name": "Mark", "value": value}}


async def approved_plan(approval, actions, review=None) -> str:
    args: Dict[str, Any] = {"actions": actions}
    if review:
        args["review"] = review
    plan = await approval.execute_tool("plan_actions", args)
    await panel_decide(approval, "approve_plan", plan["plan_id"])
    return plan["plan_id"]


def writes(addin: FakeAddin) -> list:
    return [c for c in addin.single if c[0] != "revit.get_parameter_value"]


@pytest.mark.anyio
async def test_batchable_plan_runs_as_one_batch_and_every_action_is_recorded(tmp_path):
    approval, _revit, addin = make(tmp_path)
    move = {"tool": "revit_move_element", "arguments": {"element_id": 3, "x": 1.0, "y": 0.0}}
    plan_id = await approved_plan(approval, [mark(1, "X"), mark(2, "Y"), move], review={"summary": "Renumber\nmarks"})

    reply = await approval.execute_tool("execute_plan", {"plan_id": plan_id})

    assert reply["ok"] is True and reply["state"] == "executed" and reply["batched"] is True
    assert reply["undo"] == {"one_step": True, "group_name": f"AEC Model Bridge: Renumber marks ({plan_id[5:13]})"}
    assert len(addin.batches) == 1 and writes(addin) == []
    sent = addin.batches[0]
    assert sent["plan_id"] == plan_id and sent["title"] == "Renumber marks"
    assert [a["tool"] for a in sent["actions"]] == ["revit.set_parameter_value", "revit.set_parameter_value",
                                                    "revit.move_element"]
    assert sent["actions"][2]["payload"] == {"element_id": 3, "vector": {"x": 1.0, "y": 0.0, "z": 0}}
    plan = approval.gate.load_plan(plan_id)
    assert [a["action_id"] for a in sent["actions"]] == [a["action_id"] for a in plan["actions"]]
    assert [a["state"] for a in plan["actions"]] == ["executed"] * 3
    assert [r["action_id"] for r in reply["results"]] == [a["action_id"] for a in plan["actions"]]
    assert addin.values[1]["Mark"] == "X" and addin.values[2]["Mark"] == "Y"
    assert approval.gate.load_proof(plan_id)["outcome"] == "success"


@pytest.mark.anyio
async def test_every_action_is_claimed_before_the_batch_is_sent(tmp_path):
    approval, _revit, addin = make(tmp_path)
    plan_id = await approved_plan(approval, [mark(1, "X"), mark(2, "Y")])
    seen: list = []
    addin.on_batch = lambda: seen.extend(a["state"] for a in approval.gate.load_plan(plan_id)["actions"])

    await approval.execute_tool("execute_plan", {"plan_id": plan_id})

    assert seen == ["running", "running"]
    # Consumed: a second run, or a direct call with the same arguments, is refused.
    with pytest.raises(ValueError, match="not 'approved'"):
        await approval.execute_tool("execute_plan", {"plan_id": plan_id})
    with pytest.raises(BridgeError):
        approval.gate.claim_action("revit_set_parameter_value", {**mark(1, "X")["arguments"], "plan_id": plan_id})


@pytest.mark.anyio
async def test_mid_plan_failure_rolls_back_and_records_every_action_failed(tmp_path):
    approval, _revit, addin = make(tmp_path)
    addin.fail_element = 2
    plan_id = await approved_plan(approval, [mark(1, "X"), mark(2, "Y"), mark(3, "Z")])

    reply = await approval.execute_tool("execute_plan", {"plan_id": plan_id})

    assert reply["ok"] is False and reply["batched"] is True and reply["undo"]["one_step"] is False
    assert addin.values == {1: {"Mark": "A"}, 2: {"Mark": "B"}, 3: {"Mark": "C"}}, "the group rollback undid action 1"
    first, failed, rest = reply["results"]
    assert first["rolled_back"] is True and "error" in first
    assert failed["error"] == "Parameter 'Mark' is read-only" and "rolled_back" not in failed
    assert rest["not_run"] is True and "error" in rest
    plan = approval.gate.load_plan(plan_id)
    assert plan["state"] == "partial"
    assert [a["state"] for a in plan["actions"]] == ["failed", "failed", "failed"]
    assert plan["actions"][0]["error"] == "Rolled back" and plan["actions"][2]["error"] == "Not run"
    assert approval.gate.load_proof(plan_id)["outcome"] == "failed"
    assert writes(addin) == []
    with pytest.raises(ValueError, match="not 'approved'"):
        await approval.execute_tool("execute_plan", {"plan_id": plan_id})


@pytest.mark.anyio
async def test_addin_without_the_command_runs_one_action_at_a_time(tmp_path):
    approval, _revit, addin = make(tmp_path, FakeAddin(supports=False))
    plan_id = await approved_plan(approval, [mark(1, "X"), mark(2, "Y")])

    reply = await approval.execute_tool("execute_plan", {"plan_id": plan_id})

    assert reply["state"] == "executed" and "batched" not in reply and "undo" not in reply
    assert addin.batches == []
    assert [c[0] for c in writes(addin)] == ["revit.set_parameter_value", "revit.set_parameter_value"]


@pytest.mark.anyio
async def test_addin_without_the_command_keeps_report_and_continue(tmp_path):
    approval, _revit, addin = make(tmp_path, FakeAddin(supports=False))
    addin.fail_element = 1
    plan_id = await approved_plan(approval, [mark(1, "X"), mark(2, "Y")])

    reply = await approval.execute_tool("execute_plan", {"plan_id": plan_id})

    assert reply["state"] == "partial" and addin.values[2]["Mark"] == "Y"
    assert [a["state"] for a in approval.gate.load_plan(plan_id)["actions"]] == ["failed", "executed"]


@pytest.mark.anyio
async def test_plan_with_a_non_batchable_action_runs_one_action_at_a_time(tmp_path):
    approval, _revit, addin = make(tmp_path)
    delete = {"tool": "revit_delete_element", "arguments": {"element_id": 3}}
    assert delete["tool"] not in PLAN_BATCH_TOOLS
    plan_id = await approved_plan(approval, [mark(1, "X"), delete])

    reply = await approval.execute_tool("execute_plan", {"plan_id": plan_id})

    assert reply["state"] == "executed" and "batched" not in reply
    assert addin.batches == []
    assert [c[0] for c in writes(addin)] == ["revit.set_parameter_value", "revit.delete_element"]


@pytest.mark.anyio
async def test_payload_outside_the_contract_runs_one_action_at_a_time(tmp_path):
    approval, revit, addin = make(tmp_path)
    plan_id = await approved_plan(approval, [mark(1, "X"), mark(2, "Y")])
    plan = approval.gate.load_plan(plan_id)
    assert revit.plan_batch_members(plan_id, plan["actions"]) is not None
    bad = [dict(plan["actions"][0], arguments={"element_id": "not a number", "parameter_name": "Mark", "value": 1})]
    assert revit.plan_batch_members(plan_id, bad) is None
    too_many = [plan["actions"][0]] * (MAX_PLAN_BATCH_ACTIONS + 1)
    assert revit.plan_batch_members(plan_id, too_many) is None


@pytest.mark.anyio
async def test_mock_mode_never_batches(tmp_path):
    revit = RevitProvider(workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.mock)
    action = {"action_id": "act_1", **mark(1, "X")}
    assert revit.plan_batch_members("plan_1", [action]) is None


@pytest.mark.anyio
async def test_batch_that_raises_records_every_claimed_action_failed(tmp_path):
    approval, _revit, addin = make(tmp_path)
    addin.batch_raises = CommandFailed("Bridge error: The active document is read-only, so the plan cannot run.")
    plan_id = await approved_plan(approval, [mark(1, "X"), mark(2, "Y")])

    reply = await approval.execute_tool("execute_plan", {"plan_id": plan_id})

    assert reply["ok"] is False and reply["state"] == "partial"
    assert all("read-only" in r["error"] for r in reply["results"])
    assert [a["state"] for a in approval.gate.load_plan(plan_id)["actions"]] == ["failed", "failed"]


@pytest.mark.anyio
async def test_mismatched_batch_result_fails_closed(tmp_path):
    approval, _revit, addin = make(tmp_path)
    addin.batch_reply = {"committed": True, "results": [{"action_id": "act_other", "ok": True}]}
    plan_id = await approved_plan(approval, [mark(1, "X"), mark(2, "Y")])

    reply = await approval.execute_tool("execute_plan", {"plan_id": plan_id})

    assert reply["ok"] is False
    assert all("does not match" in r["error"] for r in reply["results"])
    assert [a["state"] for a in approval.gate.load_plan(plan_id)["actions"]] == ["failed", "failed"]


@pytest.mark.anyio
async def test_batch_still_running_leaves_actions_running_and_writes_no_proof(tmp_path):
    approval, _revit, addin = make(tmp_path)
    addin.batch_reply = {"status": "running", "request_id": "req-1"}
    plan_id = await approved_plan(approval, [mark(1, "X"), mark(2, "Y")])

    reply = await approval.execute_tool("execute_plan", {"plan_id": plan_id})

    plan = approval.gate.load_plan(plan_id)
    assert [a["state"] for a in plan["actions"]] == ["running", "running"]
    assert plan["state"] == "approved"
    assert len(reply["pending_results"]) == 2 and reply["batch_request_id"] == "req-1"
    assert "approval CLI" in reply["pending_results"][0]["resume"]
    assert approval.gate.load_proof(plan_id) is None
    # Never replayed: a second run sends nothing and reports the running actions.
    again = await approval.execute_tool("execute_plan", {"plan_id": plan_id})
    assert len(addin.batches) == 1 and len(again["pending_results"]) == 2


@pytest.mark.anyio
async def test_partly_consumed_plan_uses_the_one_by_one_path(tmp_path):
    approval, _revit, addin = make(tmp_path)
    plan_id = await approved_plan(approval, [mark(1, "X")])
    approval.gate.claim_action("revit_set_parameter_value", {**mark(1, "X")["arguments"], "plan_id": plan_id})
    # The direct claim consumed the only action, so execute_plan uses today's path and sends nothing.
    reply = await approval.execute_tool("execute_plan", {"plan_id": plan_id})
    assert addin.batches == [] and writes(addin) == []
    assert reply["pending_results"]


# --------------------------------------------------------------------------- bridge client


class PlanBatchHttp:
    def __init__(self, answers: list) -> None:
        self.answers = answers
        self.requests: list = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body))
        return httpx.Response(200, json=self.answers.pop(0))


def client_for(http: PlanBatchHttp, catalog) -> BridgeClient:
    client = BridgeClient("http://bridge.test", timeout=30, token="tok")
    client._http = httpx.Client(transport=httpx.MockTransport(http.handler))
    client._http_key = (client.token, client.timeout)
    client._tool_catalog = catalog
    client._sleep = lambda _s: None
    return client


def test_client_supports_plan_batch_only_when_the_addin_lists_it():
    assert client_for(PlanBatchHttp([]), [PLAN_BATCH_COMMAND]).supports_plan_batch() is True
    assert client_for(PlanBatchHttp([]), ["revit.batch"]).supports_plan_batch() is False
    assert client_for(PlanBatchHttp([]), None).supports_plan_batch() is False


def test_client_sends_one_request_and_normalises_results():
    result = {"committed": True, "results": [{"action_id": "act_1", "ok": True, "result": {"wall_id": 9}}]}
    http = PlanBatchHttp([{"Status": "ok", "Tool": PLAN_BATCH_COMMAND, "Result": result}])
    client = client_for(http, [PLAN_BATCH_COMMAND])
    actions = [{"action_id": "act_1", "tool": "revit.move_element",
                "payload": {"element_id": 9, "vector": {"x": 1, "y": 0, "z": 0}}}]

    answer = client.call_plan_batch("plan_abc", "Move", actions)

    assert answer["results"][0]["result"]["element_id"] == 9
    (_method, path, body), = http.requests
    assert path == "/execute" and body["tool"] == PLAN_BATCH_COMMAND
    assert body["payload"] == {"plan_id": "plan_abc", "title": "Move", "actions": actions}


def test_client_keeps_collecting_a_slow_batch():
    running = {"status": "running", "request_id": "r"}
    done = {"state": "done", "response": {"Status": "ok", "Result": {"committed": True, "results": []}}}
    http = PlanBatchHttp([running] + [{"state": "running"}] * 3 + [done])
    client = client_for(http, [PLAN_BATCH_COMMAND])
    client.soft_wait = 0.001
    answer = client.call_plan_batch("plan_abc", "t", [{"action_id": "a", "tool": "revit.move_element",
                                                         "payload": {"element_id": 1, "vector": {"x": 0, "y": 0}}}])
    assert answer["committed"] is True


def test_client_refuses_an_empty_or_oversized_batch_before_sending():
    http = PlanBatchHttp([])
    client = client_for(http, [PLAN_BATCH_COMMAND])
    with pytest.raises(ValueError):
        client.call_plan_batch("plan_abc", "t", [])
    with pytest.raises(ValueError):
        client.call_plan_batch("plan_abc", "t", [{"action_id": "a", "tool": "revit.move_element", "payload": {}}]
                               * (MAX_PLAN_BATCH_ACTIONS + 1))
    assert http.requests == []


# --------------------------------------------------------------------------- add-in agreement


def test_batchable_commands_agree_with_the_addin_and_the_contract():
    source = (BRIDGE_SRC / "PlanBatch.cs").read_text(encoding="utf-8")
    block = source[source.index("_batchable = new("):]
    block = block[: block.index("};")]
    assert set(re.findall(r'"(revit\.[a-z_]+)"', block)) == set(PLAN_BATCH_COMMANDS)
    assert f"MaxActions = {MAX_PLAN_BATCH_ACTIONS};" in source
    schema = contract.COMMANDS[PLAN_BATCH_COMMAND]
    assert schema["is_mutating"] is True
    item = schema["params"]["properties"]["actions"]["items"]
    assert set(item["properties"]["tool"]["enum"]) == set(PLAN_BATCH_COMMANDS)
    assert schema["params"]["properties"]["actions"]["maxItems"] == MAX_PLAN_BATCH_ACTIONS


def test_addin_command_uses_one_group_assimilates_and_rolls_back():
    source = (BRIDGE_SRC / "PlanBatchCommand.cs").read_text(encoding="utf-8")
    assert re.search(r'\[BridgeCommand\("revit\.execute_plan_batch", IsMutating = true\)\]', source)
    body = source[source.index("private static object ExecutePlanBatch("):]
    assert body.index("PlanBatch.Parse(payload, IsRegisteredCommand)") < body.index("new TransactionGroup(")
    assert body.index("new TransactionGroup(") < body.index("Execute(app, action.Tool, action.Payload)")
    assert "group.Assimilate()" in body and "SafeRollBack(group)" in body
    assert "PlanBatch.TimeBudgetMs" in body
    assert "break;" in body, "the run must stop at the first failure"
    assert "doc.IsModifiable" in body, "an open transaction must refuse the batch before the group starts"
