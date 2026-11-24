"""Plan preview, blast radius and the workspace policy. None of these approve or run anything."""
from __future__ import annotations

import json

import pytest

from revit_mcp_server.errors import BridgeError
from revit_mcp_server.providers.approval_provider import ApprovalProvider
from revit_mcp_server.providers.registry import ProviderRegistry
from revit_mcp_server.security import plan_review as pr
from revit_mcp_server.security import policy as pol
from revit_mcp_server.security.workspace import WorkspaceMonitor
from helpers import panel_decide
from test_approval_provider import FakeParamStore

SET = "revit_set_parameter_value"


def act(eid, param="FireRating", value="60", tool=SET, **extra):
    return {"tool": tool, "arguments": {"element_id": eid, "parameter_name": param, "value": value, **extra}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv(pol.POLICY_ENV, raising=False)
    registry = ProviderRegistry()
    approval = ApprovalProvider(workspace=WorkspaceMonitor([tmp_path]), registry=registry, approval_mode="required")
    registry.register(approval)
    registry.register(FakeParamStore({1: {"FireRating": "30", "Mark": ""}, 2: {"FireRating": "45"}}))
    return approval, tmp_path


# ---- preview ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_preview_rows_match_diff(env):
    approval, _ = env
    plan = await approval.execute_tool("plan_actions", {"actions": [act(1), act(2, value="90")]})
    rows = plan["preview"]["rows"]
    assert [(r["element_id"], r["parameter"], r["before"], r["after"], r["tool"]) for r in rows] == [
        ("1", "FireRating", "30", "60", SET), ("2", "FireRating", "45", "90", SET)]
    for action, row in zip(plan["actions"], rows):
        assert row["action_id"] == action["action_id"]
    listed = (await approval.execute_tool("list_pending_plans", {}))["plans"][0]
    assert listed["preview"] == plan["preview"] and listed["preview_markdown"] == plan["preview_markdown"]


@pytest.mark.anyio
async def test_preview_does_not_change_the_hash(env):
    approval, _ = env
    plan = await approval.execute_tool("plan_actions", {"actions": [act(1)]})
    stored = approval.gate.load_plan(plan["plan_id"])
    assert "preview" not in stored and "blast_radius" not in stored
    assert stored["plan_hash"] == plan["plan_hash"]


@pytest.mark.anyio
async def test_empty_before_renders_as_empty(env):
    approval, _ = env
    plan = await approval.execute_tool("plan_actions", {"actions": [act(1, param="Mark", value="A")]})
    assert plan["preview"]["rows"][0]["before"] == "(empty)"
    assert "| (empty) |" in plan["preview_markdown"]


def test_uncaptured_before_is_not_called_empty():
    plan = {"actions": [{"action_id": "a", "tool": "revit_delete_element",
                         "arguments": {"element_id": 5}, "diff": {"before": {}, "after": {"element_id": 5}}}]}
    row = pr.preview_rows(plan)[0]
    assert row["before"] == "(not captured)" and row["element_id"] == "5"


def test_markdown_is_capped_and_escaped():
    plan = {"actions": [{"action_id": f"a{i}", "tool": SET,
                         "arguments": {"element_id": i, "parameter_name": "A|B", "value": "x|y"},
                         "diff": {"before": {str(i): {"A|B": "o"}},
                                  "after": {"element_id": i, "parameter_name": "A|B", "value": "x|y"}}}
                        for i in range(40)]}
    md = pr.preview_markdown(pr.preview_rows(plan), pr.blast_radius(plan))
    assert len(md.splitlines()) == 4 + pr.MARKDOWN_MAX_ROWS + 2
    assert "15 more row(s) not shown." in md
    assert "A\\|B" in md and "x\\|y" in md


def test_uid_and_fields_from_snapshot(tmp_path):
    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir()
    (snap_dir / "snap1.json").write_text(json.dumps({"elements": [
        {"element_id": 7, "uid": "U-7", "category": "OST_Walls", "level": "L1"}]}))
    plan = {"snapshot_id": "snap1", "actions": [act(7), act(8)]}
    index = pr.snapshot_index(tmp_path, "snap1")
    rows = pr.preview_rows(plan, index)
    assert rows[0]["unique_id"] == "U-7" and rows[1]["unique_id"] is None
    r = pr.blast_radius(plan, index)
    assert r["categories"] == ["OST_Walls", "unknown"]
    assert r["levels"] == ["L1", "unknown"] and r["worksets"] == ["unknown"]


# ---- blast radius ----------------------------------------------------------------------
def test_counts_dedupe_elements_and_report_unknown():
    plan = {"actions": [act(1), act(1, param="Mark"), act(2, category="Walls", level="L2")]}
    r = pr.blast_radius(plan)
    assert (r["element_count"], r["action_count"], r["unidentified_actions"]) == (2, 3, 0)
    assert r["categories"] == ["Walls", "unknown"] and r["levels"] == ["L2", "unknown"]
    assert r["worksets"] == ["unknown"]


def test_known_values_have_no_unknown():
    r = pr.blast_radius({"actions": [act(1, category="Walls", level="L1", workset="W")]})
    assert r["categories"] == ["Walls"] and r["levels"] == ["L1"] and r["worksets"] == ["W"]


def _plan(elements, actions):
    """`actions` actions that together name exactly `elements` elements."""
    acts = [act(i) for i in range(actions - 1)]
    rest = list(range(actions - 1, elements)) or [0]
    acts.append({"tool": SET, "arguments": {"element_ids": rest}})
    return {"actions": acts}


@pytest.mark.parametrize("elements,actions,risk", [
    (1, 1, "low"), (10, 5, "low"), (11, 5, "medium"), (6, 6, "medium"),
    (100, 25, "medium"), (101, 25, "high"), (26, 26, "high"),
])
def test_risk_thresholds(elements, actions, risk):
    plan = _plan(elements, actions)
    r = pr.blast_radius(plan)
    assert r["element_count"] == elements and r["action_count"] == actions
    assert r["risk"] == risk


def test_unidentified_and_delete_raise_risk_to_medium():
    assert pr.blast_radius({"actions": [{"tool": "revit_execute_python", "arguments": {"script": "x"}}]})["risk"] == "medium"
    assert pr.blast_radius({"actions": [{"tool": "revit_delete_element", "arguments": {"element_id": 1}}]})["risk"] == "medium"


@pytest.mark.anyio
async def test_header_has_risk(env):
    approval, _ = env
    plan = await approval.execute_tool("plan_actions", {"actions": [act(1)]})
    assert plan["blast_radius"]["risk"] == "low"
    assert plan["preview_markdown"].startswith("**Risk: low** - 1 element(s), 1 action(s).")


# ---- policy ----------------------------------------------------------------------------
def write_policy(tmp_path, text, name="policy.yaml"):
    (tmp_path / name).write_text(text, encoding="utf-8")


@pytest.mark.anyio
async def test_no_policy_file_changes_nothing(env):
    approval, _ = env
    plan = await approval.execute_tool("plan_actions", {"actions": [act(1)]})
    assert "policy_hash" not in plan
    assert (await approval.execute_tool("policy_show", {}))["active"] is False


@pytest.mark.anyio
@pytest.mark.parametrize("text,match", [
    ("blocked_tools: [revit_set_parameter_value]", "blocked_tools"),
    ("allowed_tools: [revit_get_levels]", "not in allowed_tools"),
    ("blocked_parameters: [fireRATING]", "blocked_parameters"),
    ("allowed_categories: [Doors]", "allowed_categories"),
    ("max_actions_per_plan: 1", "max_actions_per_plan"),
    ("max_elements_per_plan: 1", "max_elements_per_plan"),
])
async def test_each_rule_refuses_at_draft(env, text, match):
    approval, tmp = env
    write_policy(tmp, text)
    actions = [act(1, category="Walls"), act(2, category="Walls")]
    with pytest.raises(BridgeError, match=match):
        await approval.execute_tool("plan_actions", {"actions": actions})
    assert approval.gate.list_pending_plans() == []


@pytest.mark.anyio
async def test_allowed_category_and_unknown_category(env):
    approval, tmp = env
    write_policy(tmp, "allowed_categories: [walls]")
    plan = await approval.execute_tool("plan_actions", {"actions": [act(1, category="OST_Walls")]})
    assert plan["policy_hash"].startswith("sha256:")
    assert approval.gate.load_plan(plan["plan_id"])["policy_hash"] == plan["policy_hash"]
    with pytest.raises(BridgeError, match="unknown"):
        await approval.execute_tool("plan_actions", {"actions": [act(1)]})


@pytest.mark.anyio
async def test_execute_rechecks_a_tightened_policy(env):
    approval, tmp = env
    plan = await approval.execute_tool("plan_actions", {"actions": [act(1)]})
    await panel_decide(approval, "approve_plan", plan["plan_id"])
    write_policy(tmp, "blocked_tools: [revit_set_parameter_value]")
    with pytest.raises(BridgeError, match="blocked_tools"):
        await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    stored = approval.gate.load_plan(plan["plan_id"])
    assert stored["state"] == "approved" and stored["actions"][0]["state"] == "pending"
    (tmp / "policy.yaml").unlink()
    assert (await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]}))["state"] == "executed"


@pytest.mark.anyio
@pytest.mark.parametrize("text", ["blocked_tools: [a", "unknown_rule: 1", "max_actions_per_plan: -1",
                                  "blocked_tools: nope", "- a\n- b"])
async def test_invalid_policy_refuses_writes(env, text):
    approval, tmp = env
    write_policy(tmp, text)
    with pytest.raises(BridgeError, match="Invalid policy file"):
        await approval.execute_tool("plan_actions", {"actions": [act(1)]})
    with pytest.raises(BridgeError, match="Invalid policy file"):
        await approval.execute_tool("policy_show", {})


@pytest.mark.anyio
async def test_invalid_policy_refuses_execute_of_existing_plan(env):
    approval, tmp = env
    plan = await approval.execute_tool("plan_actions", {"actions": [act(1)]})
    await panel_decide(approval, "approve_plan", plan["plan_id"])
    write_policy(tmp, "{{{")
    with pytest.raises(BridgeError, match="Invalid policy file"):
        await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})


@pytest.mark.anyio
async def test_env_file_json_and_missing_env_file(env, monkeypatch):
    approval, tmp = env
    f = tmp / "elsewhere.json"
    f.write_text(json.dumps({"max_actions_per_plan": 5}))
    monkeypatch.setenv(pol.POLICY_ENV, str(f))
    shown = await approval.execute_tool("policy_show", {})
    assert shown["rules"] == {"max_actions_per_plan": 5} and shown["source"] == str(f)
    monkeypatch.setenv(pol.POLICY_ENV, str(tmp / "missing.yaml"))
    with pytest.raises(BridgeError, match="Invalid policy file"):
        await approval.execute_tool("plan_actions", {"actions": [act(1)]})


def test_documented_example_policy_is_valid(tmp_path, monkeypatch):
    from pathlib import Path
    example = Path(__file__).resolve().parents[3] / "docs" / "examples" / "policy.yaml"
    monkeypatch.setenv(pol.POLICY_ENV, str(example))
    p = pol.load_policy(tmp_path)
    assert p.active and p.rules["max_actions_per_plan"] == 20 and "revit_execute_python" in p.rules["blocked_tools"]


def test_policy_hash_is_stable_across_formatting(tmp_path, monkeypatch):
    monkeypatch.delenv(pol.POLICY_ENV, raising=False)
    write_policy(tmp_path, "blocked_tools: [b, a]\nmax_actions_per_plan: 3\n")
    h1 = pol.load_policy(tmp_path).hash
    write_policy(tmp_path, "max_actions_per_plan: 3\n# c\nblocked_tools:\n  - a\n  - b\n")
    assert pol.load_policy(tmp_path).hash == h1
