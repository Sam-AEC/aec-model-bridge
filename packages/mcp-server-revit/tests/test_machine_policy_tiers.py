"""Machine policy, merge rule, tiers and the Dev mode override (issue #363)."""
from __future__ import annotations

import asyncio
import json

import pytest

from revit_mcp_server import doctor, mcp_server
from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security import dev_mode as dev
from revit_mcp_server.security import policy as pol
from revit_mcp_server.security import tiers
from revit_mcp_server.security.workspace import WorkspaceMonitor

TOKEN = "A" * 43
SET = "revit_set_parameter_value"


def machine(tmp_path, monkeypatch, text):
    f = tmp_path / "machine" / "policy.yaml"
    f.parent.mkdir(exist_ok=True)
    f.write_text(text, encoding="utf-8")
    monkeypatch.setenv(pol.MACHINE_POLICY_ENV, str(f))
    return f


def workspace(tmp_path, text):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    (ws / "policy.yaml").write_text(text, encoding="utf-8")
    return ws


@pytest.fixture
def server(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.delenv(pol.POLICY_ENV, raising=False)
    registry, approval, job_manager, _m, _w = build_registry(WorkspaceMonitor([ws]))
    approval.gate.override_token = TOKEN
    monkeypatch.setattr(mcp_server, "registry", registry)
    monkeypatch.setattr(mcp_server, "approval_provider", approval)
    monkeypatch.setattr(mcp_server, "job_manager", job_manager)
    return registry, approval, ws


def listed():
    return {t.name for t in asyncio.run(mcp_server.list_tools())}


def call(name, args=None):
    result = asyncio.run(mcp_server.call_tool(name, args or {}))
    return json.dumps(getattr(result, "model_dump", lambda **k: result)(), default=str)


# ---- machine file -----------------------------------------------------------------------
def test_missing_file_at_default_location_is_no_policy(tmp_path, monkeypatch):
    monkeypatch.setattr(pol, "_platform_default", lambda: str(tmp_path / "absent.yaml"))
    assert pol.load_policy(tmp_path).active is False


def test_platform_default_paths():
    assert pol.default_machine_path(False, None) == "/etc/aec-model-bridge/policy.yaml"
    assert pol.default_machine_path(True, "C:\\ProgramData") == "C:\\ProgramData\\AECModelBridge\\policy.yaml"
    assert pol.default_machine_path(True, None) is None


def test_default_location_is_used_without_env(monkeypatch, tmp_path):
    monkeypatch.delenv(pol.MACHINE_POLICY_ENV, raising=False)
    monkeypatch.setattr(pol, "_platform_default", lambda: str(tmp_path / "p.yaml"))
    assert pol.machine_policy_path() is None
    (tmp_path / "p.yaml").write_text("blocked_tools: [x]")
    assert pol.machine_policy_path() == tmp_path / "p.yaml"


def test_missing_file_named_by_env_fails_closed(tmp_path, monkeypatch):
    """A typo or a deleted file must not switch the machine policy off."""
    monkeypatch.setenv(pol.MACHINE_POLICY_ENV, str(tmp_path / "typo-policy.yaml"))
    assert pol.machine_policy_path() == tmp_path / "typo-policy.yaml"
    with pytest.raises(pol.PolicyError, match="Invalid policy file"):
        pol.load_policy(tmp_path)


@pytest.mark.parametrize("text", ["blocked_tools: [a", "nonsense: 1", "allowed_tiers: [admin]", "- a\n- b"])
def test_invalid_machine_file_fails_closed(tmp_path, monkeypatch, text):
    machine(tmp_path, monkeypatch, text)
    with pytest.raises(pol.PolicyError, match="Invalid policy file"):
        pol.load_policy(tmp_path / "ws")


def test_unreadable_machine_file_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv(pol.MACHINE_POLICY_ENV, str(tmp_path))  # a folder: cannot be read as a file
    with pytest.raises(pol.PolicyError):
        pol.load_policy(tmp_path / "ws")


# ---- merge: stricter wins ---------------------------------------------------------------
def test_merge_rules(tmp_path, monkeypatch):
    machine(tmp_path, monkeypatch, "blocked_tools: [a]\nallowed_tools: [x, y]\nmax_actions_per_plan: 5\n"
                                   "allowed_tiers: [read, write]\nallowed_categories: [walls, doors]")
    ws = workspace(tmp_path, "blocked_tools: [b]\nallowed_tools: [y, z]\nmax_actions_per_plan: 9\n"
                             "blocked_tiers: [write]\nallowed_categories: [OST_Walls]")
    p = pol.load_policy(ws)
    r = p.rules
    assert r["blocked_tools"] == ["a", "b"] and r["allowed_tools"] == ["y"]
    assert r["max_actions_per_plan"] == 5 and r["allowed_categories"] == ["walls"]
    assert set(pol.tiers_off(p)) == {"script", "export", "write"}


def test_workspace_cannot_loosen_machine(tmp_path, monkeypatch):
    mf = machine(tmp_path, monkeypatch, "blocked_tools: [a]\nmax_actions_per_plan: 1\nallowed_tiers: [read]")
    ws = workspace(tmp_path, "blocked_tools: []\nmax_actions_per_plan: 100\nallowed_tiers: [read, write, script, export]")
    p = pol.load_policy(ws)
    assert p.rules["blocked_tools"] == ["a"] and p.rules["max_actions_per_plan"] == 1
    assert pol.tiers_off(p) == {t: str(mf) for t in ("write", "script", "export")}
    assert "machine policy file" in pol.tier_refusal(p, "x", "write")
    with pytest.raises(pol.PolicyError, match="blocked_tools"):
        pol.check_actions(p, [{"tool": "a", "arguments": {}}])


def test_one_file_keeps_its_own_hash(tmp_path):
    ws = workspace(tmp_path, "blocked_tools: [a]")
    p = pol.load_policy(ws)
    assert len(p.layers) == 1 and p.hash == p.layers[0].hash


def test_bad_workspace_file_with_good_machine_file_fails_closed(tmp_path, monkeypatch):
    machine(tmp_path, monkeypatch, "blocked_tools: [a]")
    ws = workspace(tmp_path, "blocked_tools: [")
    with pytest.raises(pol.PolicyError):
        pol.load_policy(ws)


# ---- tiers ------------------------------------------------------------------------------
def test_every_registered_tool_has_exactly_one_tier(server):
    registry, _a, _w = server
    seen = {}
    for provider, tool in registry.get_tools_with_providers():
        t = tiers.tier_of(tool.name, tool, provider.get_identity())
        assert t in tiers.TIERS, tool.name
        seen[tool.name] = t
    assert len(seen) > 150
    assert set(seen.values()) == set(tiers.TIERS)
    for provider, tool in registry.get_tools_with_providers():
        if tool.is_mutating and tool.name not in tiers.CONTROL_TOOLS:
            assert seen[tool.name] in ("write", "script"), tool.name
    # Entries that name a tool in an always-present provider must still exist (no stale names).
    for name in tiers.WRITE_TOOLS | {"revit_execute_python", "revit_run_job", "policy_show", "list_pending_plans"}:
        assert name in seen, f"stale tier entry {name}"


def test_tool_without_metadata_has_no_tier():
    with pytest.raises(ValueError):
        tiers.tier_of("new_tool", None)
    with pytest.raises(ValueError):
        tiers.tier_of("new_tool", object())


def test_control_tools_are_inside_approval_tools():
    from revit_mcp_server.result_presentation import APPROVAL_TOOLS
    assert tiers.CONTROL_TOOLS <= APPROVAL_TOOLS


def test_tier_off_hides_and_refuses(server, tmp_path, monkeypatch):
    assert {"revit_execute_python", SET, "revit_export_ifc"} <= listed()
    machine(tmp_path, monkeypatch, "allowed_tiers: [read]")
    names = listed()
    assert not names & {"revit_execute_python", SET, "revit_export_ifc", "plan_actions", "execute_plan"}
    assert {"list_pending_plans", "policy_show", "revit_health"} <= names
    for tool in ("revit_execute_python", SET, "revit_export_ifc", "plan_actions"):
        msg = call(tool)
        assert "policy_refused" in msg and "machine policy file" in msg and "tier is off" in msg
    assert "policy_refused" not in call("policy_show")  # control tools stay callable
    assert "human_only" in call("reject_plan", {"plan_id": "x"})  # a person's tool; policy never blocks it


def test_workspace_file_turns_tier_off_and_names_file(server):
    _r, _a, ws = server
    workspace(ws.parent, "blocked_tiers: [script]")
    assert "revit_execute_python" not in listed() and SET in listed()
    msg = call("revit_execute_python")
    assert "workspace policy file" in msg and "script tier" in msg


def test_invalid_policy_hides_everything_but_reads(server, tmp_path, monkeypatch):
    machine(tmp_path, monkeypatch, "oops: [")
    names = listed()
    assert "revit_health" in names and SET not in names and "revit_execute_python" not in names
    assert "Invalid policy file" in call(SET)


def test_plan_with_script_action_refused_when_script_tier_off(tmp_path, monkeypatch, server):
    machine(tmp_path, monkeypatch, "blocked_tiers: [script]")
    p = pol.load_policy(tmp_path / "ws")
    with pytest.raises(pol.PolicyError, match="script tier"):
        pol.check_actions(p, [{"tool": "revit_execute_python", "arguments": {}}])
    pol.check_actions(p, [{"tool": SET, "arguments": {}}])  # write tier is on


# ---- Dev mode override ------------------------------------------------------------------
def test_dev_mode_lifts_tier_limits_and_audits(server, tmp_path, monkeypatch):
    _r, approval, ws = server
    machine(tmp_path, monkeypatch, "allowed_tiers: [read]")
    assert "revit_execute_python" not in listed()
    dev.enable_dev(ws, token=TOKEN)
    assert approval.gate.dev_mode
    assert {"revit_execute_python", SET} <= listed()
    assert "policy_refused" not in call("revit_execute_python", {})
    lines = [json.loads(x) for x in (ws / dev.AUDIT_FILENAME).read_text().splitlines()]
    bypass = [x for x in lines if x["event"] == "policy_bypassed"]
    assert bypass and bypass[0]["tool"] == "revit_execute_python" and "machine policy file" in bypass[0]["rule"]
    dev.disable_dev(ws)
    assert "revit_execute_python" not in listed()


def test_dev_mode_does_not_lift_invalid_file(server, tmp_path, monkeypatch):
    _r, _a, ws = server
    machine(tmp_path, monkeypatch, "oops: [")
    dev.enable_dev(ws, token=TOKEN)
    assert SET not in listed()


def test_dev_mode_audits_plan_limit_bypass(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    machine(tmp_path, monkeypatch, "blocked_tools: [a]")
    dev.enable_dev(ws, token=TOKEN)
    p = pol.load_policy(ws)
    with pytest.raises(pol.PolicyError):
        pol.check_actions(p, [{"tool": "a", "arguments": {}}], ws)
    pol.check_actions(p, [{"tool": "a", "arguments": {}}], ws, dev_mode=True)
    events = [json.loads(x) for x in (ws / dev.AUDIT_FILENAME).read_text().splitlines()]
    assert events[-1]["event"] == "policy_bypassed" and "blocked_tools" in events[-1]["rule"]


def test_no_model_facing_dev_switch(server):
    registry, _a, _w = server
    assert not [t.name for t in registry.get_all_tools() if "dev_mode" in t.name]


# ---- doctor -----------------------------------------------------------------------------
def test_doctor_shows_files_hashes_tiers_and_dev(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    mf = tmp_path / "m.yaml"
    mf.write_text("blocked_tiers: [script]")
    (ws / "policy.yaml").write_text("blocked_tools: [a]")
    env = {"MCP_REVIT_MODE": "mock", "MCP_REVIT_WORKSPACE_DIR": str(ws), pol.MACHINE_POLICY_ENV: str(mf)}
    check = doctor.check_policy(doctor._load_config(env), env)
    assert str(mf) in check.detail and "sha256:" in check.detail and "script (off in" in check.detail
    assert "not active" in check.detail and check.status == doctor.OK
    mf.write_text("bad: [")
    assert doctor.check_policy(doctor._load_config(env), env).status == doctor.FAIL
