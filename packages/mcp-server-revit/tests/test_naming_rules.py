"""Reviewed naming rules (#362): test a proposed rule, save it through an approved plan,
replay it with no model call. Mock mode only; UNVERIFIED against live Revit."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from revit_mcp_server.config import BridgeMode, Config, config
from revit_mcp_server.errors import BridgeError
from revit_mcp_server.module_registry import ModuleRegistry
from revit_mcp_server.providers.approval_provider import ApprovalProvider
from revit_mcp_server.providers.module_provider import ModuleProvider
from revit_mcp_server.providers.registry import ProviderRegistry
from revit_mcp_server.security.approval import HUMAN_ONLY_TOOLS
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.semantic.engine import generate_mock_snapshot

from helpers import panel_decide

SAVE = "qaqc_checker_save_naming_rule"
TEST = "qaqc_checker_test_naming_rule"
RUN = "qaqc_checker_replay_naming_rules"


def _load(relpath: str, name: str):
    p = Path(__file__).parent.parent / relpath
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_qaqc = _load("src/revit_mcp_server/modules/qaqc_checker/module.py", "_qaqc_naming_impl")


class Ws:
    def __init__(self, root: Path):
        self.allowed_directories = [root]


@pytest.fixture
def ws(tmp_path):
    return Ws(tmp_path)


@pytest.fixture
def module():
    return _qaqc.QaqcCheckerModule()


@pytest.fixture
def snapshot(tmp_path):
    snap = generate_mock_snapshot()
    d = tmp_path / "snapshots"
    d.mkdir()
    (d / f"{snap.snapshot_id}.json").write_text(snap.model_dump_json(by_alias=True), encoding="utf-8")
    return snap.snapshot_id


RULE = dict(rule_id="level_names", category="OST_Levels", regex=r"Level \d+", severity="warning",
            message="Level names are 'Level <number>'.")
STRICT = dict(RULE, rule_id="level_strict", regex=r"L-\d{2}")
PROPOSAL = {k: v for k, v in RULE.items() if k != "rule_id"}


def _findings(result):
    return [(f["rule_id"], f["element_uid"]) for f in result["findings"]]


# --- test tool ---

def test_test_rule_returns_matches_and_misses(module, ws, snapshot):
    ok = module.test_naming_rule(snapshot_id=snapshot, workspace=ws, **PROPOSAL)
    assert ok["elements_in_category"] == 2
    assert ok["matches"]["count"] == 2 and ok["misses"]["count"] == 0
    bad = module.test_naming_rule(snapshot_id=snapshot, workspace=ws, category="OST_Levels", regex=r"L-\d{2}",
                                  severity="error", message="x")
    assert bad["matches"]["count"] == 0 and bad["misses"]["count"] == 2
    assert {s["value"] for s in bad["misses"]["sample"]} == {"Level 1", "Level 2"}
    assert bad["rule_hash"] != ok["rule_hash"]


def test_test_rule_caps_sample(module, ws, snapshot):
    res = module.test_naming_rule(snapshot_id=snapshot, workspace=ws, category="OST_Levels", regex=r"L-\d{2}",
                                  severity="error", message="x", sample_limit=1)
    assert res["misses"]["count"] == 2 and len(res["misses"]["sample"]) == 1


def test_test_rule_writes_nothing(module, ws, snapshot, tmp_path):
    module.test_naming_rule(snapshot_id=snapshot, workspace=ws, category="OST_Levels", regex=r".*",
                            severity="info", message="x")
    assert not (tmp_path / "naming_rules").exists()


def test_test_rule_without_snapshot_uses_mock(module, ws, monkeypatch):
    monkeypatch.setattr(config, "mode", BridgeMode.mock)
    res = module.test_naming_rule(workspace=ws, category="OST_Levels", regex=r"Level \d+", severity="info", message="x")
    assert res["matches"]["count"] == 2


# --- refused patterns ---

@pytest.mark.parametrize("regex", [
    "(", "[a-", "*a",
    "(a+)+$", "(a*)*b", "(a|aa)+c", "(.*a){3}x", "((ab)+)*", r"(\w+\s?)+$", "(a+){2,}",
    r"(a)\1", "(?=a)a",
    "a" * 201,
    "",
    "a?" * 40 + "b", "a{0,2}" * 10 + "b",
])
def test_bad_or_catastrophic_regex_refused(module, ws, snapshot, regex):
    with pytest.raises(ValueError):
        module.test_naming_rule(snapshot_id=snapshot, workspace=ws, category="OST_Levels", regex=regex,
                                severity="error", message="x")


def test_safe_patterns_accepted(module, ws, snapshot):
    for regex in (r"[A-Z]{1,3}-\d{3}", r"(A|B)-\d+", r"(?:Level|Floor) \d+", r"[A-Za-z0-9 _-]{1,40}"):
        module.test_naming_rule(snapshot_id=snapshot, workspace=ws, category="OST_Levels", regex=regex,
                                severity="info", message="x")


def test_overlong_value_is_a_miss_not_a_regex_run(module, ws, snapshot, tmp_path):
    path = tmp_path / "snapshots" / f"{snapshot}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for el in data["elements"]:
        if el["category"] == "OST_Levels":
            el["type_name"] = "L" * 5000
    path.write_text(json.dumps(data), encoding="utf-8")
    res = module.test_naming_rule(snapshot_id=snapshot, workspace=ws, category="OST_Levels", regex=r"L+",
                                  severity="info", message="x")
    assert res["misses"]["count"] == 2


@pytest.mark.parametrize("field,value", [
    ("severity", "fatal"), ("message", ""), ("category", ""), ("target", "bogus"), ("target", "parameter"),
])
def test_bad_fields_refused(module, ws, snapshot, field, value):
    args = dict(category="OST_Levels", regex=r"Level \d+", severity="info", message="x")
    args[field] = value
    with pytest.raises(ValueError):
        module.test_naming_rule(snapshot_id=snapshot, workspace=ws, **args)


# --- save and replay ---

def test_save_writes_rule_file_with_hash(module, ws, snapshot, tmp_path):
    res = module.save_naming_rule(workspace=ws, **RULE)
    path = tmp_path / "naming_rules" / "level_names.json"
    assert res["status"] == "saved" and Path(res["path"]) == path
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["rule_hash"] == res["rule_hash"]
    assert module.test_naming_rule(snapshot_id=snapshot, workspace=ws, **PROPOSAL)["rule_hash"] == res["rule_hash"]


def test_save_refuses_overwrite_unless_asked(module, ws):
    module.save_naming_rule(workspace=ws, **RULE)
    with pytest.raises(ValueError, match="overwrite"):
        module.save_naming_rule(workspace=ws, **dict(RULE, regex=r"L\d"))
    assert module.save_naming_rule(workspace=ws, overwrite=True, **dict(RULE, regex=r"L\d"))["status"] == "saved"


def test_overwrite_does_not_follow_planted_tmp_symlink(module, ws, tmp_path):
    module.save_naming_rule(workspace=ws, **RULE)
    outside = tmp_path.parent / f"{tmp_path.name}_outside.txt"
    outside.write_text("keep", encoding="utf-8")
    try:
        (tmp_path / "naming_rules" / "level_names.json.tmp").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not permitted")
    module.save_naming_rule(workspace=ws, overwrite=True, **dict(RULE, regex=r"L\d"))
    assert outside.read_text(encoding="utf-8") == "keep"
    stored = json.loads((tmp_path / "naming_rules" / "level_names.json").read_text(encoding="utf-8"))
    assert stored["rule"]["regex"] == r"L\d"


@pytest.mark.parametrize("rule_id", ["../evil", "a/b", "a\\b", "..", ".", "", "x" * 101, "C:evil", "a b", "evil/"])
def test_path_like_rule_ids_refused(module, ws, tmp_path, rule_id):
    with pytest.raises(ValueError):
        module.save_naming_rule(workspace=ws, **dict(RULE, rule_id=rule_id))
    assert not list(tmp_path.rglob("evil*"))
    assert not (tmp_path / "naming_rules").exists()


def test_save_refuses_bad_regex(module, ws, tmp_path):
    with pytest.raises(ValueError):
        module.save_naming_rule(workspace=ws, **dict(RULE, regex="(a+)+$"))
    assert not (tmp_path / "naming_rules").exists()


def test_replay_is_deterministic_and_needs_no_model(module, ws, snapshot):
    module.save_naming_rule(workspace=ws, **STRICT)
    module.save_naming_rule(workspace=ws, **RULE)
    a = module.replay_naming_rules(snapshot_id=snapshot, workspace=ws)
    b = module.replay_naming_rules(snapshot_id=snapshot, workspace=ws)
    assert a["findings"] == b["findings"] and a["rule_hashes"] == b["rule_hashes"]
    assert a["total_findings"] == 2 and _findings(a) == sorted(_findings(a))
    assert {f["rule_id"] for f in a["findings"]} == {"level_strict"}
    assert a["findings"][0]["severity"] == "warning" and a["findings"][0]["message"] == STRICT["message"]
    assert set(a["rule_hashes"]) == {"level_strict", "level_names"}


def test_replay_matches_the_test_tool(module, ws, snapshot):
    module.save_naming_rule(workspace=ws, **STRICT)
    tested = module.test_naming_rule(snapshot_id=snapshot, workspace=ws, category="OST_Levels", regex=STRICT["regex"],
                                     severity="warning", message=STRICT["message"])
    replay = module.replay_naming_rules(snapshot_id=snapshot, workspace=ws)
    assert replay["total_findings"] == tested["misses"]["count"]
    assert replay["rule_hashes"]["level_strict"] == tested["rule_hash"]


def test_audit_entries_record_rule_hash(module, ws, snapshot, tmp_path):
    saved = module.save_naming_rule(workspace=ws, **STRICT)
    module.replay_naming_rules(snapshot_id=snapshot, workspace=ws)
    lines = [json.loads(x) for x in (tmp_path / "naming_rules_audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [e["event"] for e in lines] == ["rule_saved", "rules_run"]
    assert lines[0]["rule_hash"] == saved["rule_hash"]
    assert lines[1]["rule_hashes"] == {"level_strict": saved["rule_hash"]}
    assert lines[1]["snapshot_id"] == snapshot


def test_replay_with_no_saved_rules_is_empty(module, ws, snapshot):
    res = module.replay_naming_rules(snapshot_id=snapshot, workspace=ws)
    assert res["total_findings"] == 0 and res["rules_run"] == 0


def test_replay_can_select_rules(module, ws, snapshot):
    module.save_naming_rule(workspace=ws, **STRICT)
    module.save_naming_rule(workspace=ws, **RULE)
    res = module.replay_naming_rules(snapshot_id=snapshot, rule_ids=["level_names"], workspace=ws)
    assert res["rules_run"] == 1 and res["total_findings"] == 0
    with pytest.raises(ValueError):
        module.replay_naming_rules(snapshot_id=snapshot, rule_ids=["missing"], workspace=ws)


def test_replay_refuses_a_hand_edited_rule(module, ws, snapshot, tmp_path):
    module.save_naming_rule(workspace=ws, **RULE)
    path = tmp_path / "naming_rules" / "level_names.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["rule"]["regex"] = ".*"
    path.write_text(json.dumps(stored), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        module.replay_naming_rules(snapshot_id=snapshot, workspace=ws)


def test_replay_refuses_a_hand_edited_catastrophic_rule(module, ws, snapshot, tmp_path):
    module.save_naming_rule(workspace=ws, **RULE)
    path = tmp_path / "naming_rules" / "level_names.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["rule"]["regex"] = "(a+)+$"
    stored["rule_hash"] = _qaqc._naming_rule_hash(stored["rule"])
    path.write_text(json.dumps(stored), encoding="utf-8")
    with pytest.raises(ValueError):
        module.replay_naming_rules(snapshot_id=snapshot, workspace=ws)


# --- the plan gate ---

@pytest.fixture
def stack(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "mode", BridgeMode.mock)
    registry = ProviderRegistry()
    workspace = WorkspaceMonitor([tmp_path])
    approval = ApprovalProvider(workspace=workspace, registry=registry, approval_mode="required")
    registry.register(approval)
    cfg = Config(workspace_dir=tmp_path, allowed_directories=[tmp_path],
                 audit_log=tmp_path / "audit.log", enable_user_modules=False)
    modules = ModuleRegistry(config_obj=cfg)
    modules.discover_and_load()
    mp = ModuleProvider(module_registry=modules, workspace=workspace, tool_registry=registry)
    registry.register(mp)
    return registry, approval, mp


def _gate(registry, name, arguments, gate):
    tool_def = registry.lookup_tool(name)
    if tool_def and tool_def.is_mutating:
        gate.check_tool_execution(name, arguments)


def test_tool_flags(stack):
    registry, *_ = stack
    assert registry.lookup_tool(SAVE).is_mutating is True
    assert registry.lookup_tool(TEST).is_mutating is False
    assert registry.lookup_tool(RUN).is_mutating is False
    assert SAVE not in HUMAN_ONLY_TOOLS


def test_save_refused_without_a_plan(stack, tmp_path):
    registry, approval, _ = stack
    with pytest.raises(BridgeError, match="plan_id"):
        _gate(registry, SAVE, dict(RULE), approval.gate)
    assert not (tmp_path / "naming_rules").exists()


@pytest.mark.anyio
async def test_save_refused_with_unapproved_plan(stack, tmp_path):
    registry, approval, _ = stack
    plan = await approval.execute_tool("plan_actions", {"actions": [{"tool": SAVE, "arguments": dict(RULE)}]})
    with pytest.raises(BridgeError, match="not 'approved'"):
        _gate(registry, SAVE, {**RULE, "plan_id": plan["plan_id"]}, approval.gate)
    assert not (tmp_path / "naming_rules").exists()


@pytest.mark.anyio
async def test_save_runs_only_after_approval_and_only_as_approved(stack, tmp_path):
    registry, approval, _ = stack
    plan = await approval.execute_tool("plan_actions", {"actions": [{"tool": SAVE, "arguments": dict(RULE)}]})
    plan_id = plan["plan_id"]
    await panel_decide(approval, "approve_plan", plan_id)
    with pytest.raises(BridgeError, match="does not approve"):
        _gate(registry, SAVE, {**RULE, "regex": ".*", "plan_id": plan_id}, approval.gate)
    result = await approval.execute_tool("execute_plan", {"plan_id": plan_id})
    assert result["state"] == "executed"
    assert (tmp_path / "naming_rules" / "level_names.json").is_file()


@pytest.mark.anyio
async def test_replay_after_gated_save_via_provider(stack, tmp_path):
    registry, approval, mp = stack
    plan = await approval.execute_tool("plan_actions", {"actions": [{"tool": SAVE, "arguments": dict(STRICT)}]})
    await panel_decide(approval, "approve_plan", plan["plan_id"])
    await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    first = await mp.execute_tool(RUN, {})
    second = await mp.execute_tool(RUN, {})
    assert first["findings"] == second["findings"] and first["total_findings"] == 2
