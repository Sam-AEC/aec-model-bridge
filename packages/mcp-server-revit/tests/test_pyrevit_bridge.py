"""Tests for the pyrevit_bridge module (discovery, plan, hash-checked run)."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from revit_mcp_server.errors import BridgeError


def _load():
    p = Path(__file__).parent.parent / "src/revit_mcp_server/modules/pyrevit_bridge/module.py"
    spec = importlib.util.spec_from_file_location("_pyrevit_bridge_impl", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load()
RUN_TOOL = _mod.RUN_TOOL


class FakeWorkspace:
    def __init__(self, path):
        self.allowed_directories = [path]


WRITE_SCRIPT = '"""Renumber rooms."""\nt = Transaction(doc, "x")\nt.Start()\ndoc.Delete(1)\nt.Commit()\n'
READ_SCRIPT = "# read only\nprint(1)\n"


@pytest.fixture
def env(tmp_path, monkeypatch):
    ext_root = tmp_path / "exts"
    btn = ext_root / "Tools.extension" / "Arch.tab" / "Rooms.panel" / "Renumber Rooms.pushbutton"
    btn.mkdir(parents=True)
    (btn / "script.py").write_bytes(WRITE_SCRIPT.encode("utf-8"))
    btn2 = ext_root / "Tools.extension" / "Arch.tab" / "Rooms.panel" / "Count.pushbutton"
    btn2.mkdir(parents=True)
    (btn2 / "script.py").write_bytes(READ_SCRIPT.encode("utf-8"))
    (ext_root / "secret.py").write_text("x", encoding="utf-8")
    ws = tmp_path / "ws"
    (ws / "plans").mkdir(parents=True)
    monkeypatch.setenv(_mod.ENV_VAR, str(ext_root))
    return {"root": ext_root, "ws": FakeWorkspace(ws), "ws_dir": ws, "script": btn / "script.py"}


def _sid(env):
    return "0:Tools.extension/Arch.tab/Rooms.panel/Renumber Rooms.pushbutton/script.py"


def _approved_plan(env, sha, state="approved", plan_id="plan_abc"):
    plan = {"plan_id": plan_id, "state": state,
            "actions": [{"tool": RUN_TOOL, "arguments": {"script_id": _sid(env), "script_sha256": sha}}]}
    (env["ws_dir"] / "plans" / f"{plan_id}.json").write_text(json.dumps(plan), encoding="utf-8")
    return plan_id


def test_list_scripts(env):
    res = _mod.PyrevitBridgeModule().list_pyrevit_scripts()
    assert res["count"] == 2
    by_title = {s["title"]: s for s in res["scripts"]}
    s = by_title["Renumber Rooms"]
    assert s["id"] == _sid(env)
    assert (s["tab"], s["panel"], s["extension"]) == ("Arch", "Rooms", "Tools.extension")
    assert s["description"] == "Renumber rooms."
    assert s["has_write_calls"] is True
    assert by_title["Count"]["has_write_calls"] is False
    assert by_title["Count"]["description"] is None


def test_list_without_env(monkeypatch):
    monkeypatch.delenv(_mod.ENV_VAR, raising=False)
    assert _mod.PyrevitBridgeModule().list_pyrevit_scripts()["count"] == 0


def test_plan_has_hash_and_write_lines_and_never_executes(env):
    calls = []
    plan = _mod.PyrevitBridgeModule().plan_run_pyrevit_script(_sid(env))
    sha = hashlib.sha256(WRITE_SCRIPT.encode()).hexdigest()
    assert plan["preview"]["script_sha256"] == sha
    assert plan["requires_approval"] is True
    assert plan["preview"]["executes_on_plan"] is False
    lines = {h["line"] for h in plan["preview"]["write_call_lines"]}
    assert lines == {2, 3, 4, 5}
    assert plan["actions"][0] == {"tool": RUN_TOOL, "arguments": {"script_id": _sid(env), "script_sha256": sha}}
    assert calls == []


@pytest.mark.parametrize("bad", [
    "0:../secret.py",
    "0:Tools.extension/../secret.py",
    "0:/etc/passwd",
    "0:Tools.extension\\..\\secret.py",
    "0:secret.py",
    "5:Tools.extension/A.tab/B.pushbutton/script.py",
    "nocolon",
])
def test_traversal_and_bad_ids_rejected(env, bad):
    with pytest.raises(BridgeError):
        _mod.PyrevitBridgeModule().plan_run_pyrevit_script(bad)


def test_symlink_escape_rejected(env, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "script.py").write_text("print(1)", encoding="utf-8")
    link = env["root"] / "Evil.extension" / "Evil.pushbutton"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    sid = "0:Evil.extension/Evil.pushbutton/script.py"
    with pytest.raises(BridgeError):
        _mod.PyrevitBridgeModule().plan_run_pyrevit_script(sid)
    ids = [s["id"] for s in _mod.PyrevitBridgeModule().list_pyrevit_scripts()["scripts"]]
    assert sid not in ids


def test_run_refuses_unapproved_plan(env):
    sha = hashlib.sha256(WRITE_SCRIPT.encode()).hexdigest()
    pid = _approved_plan(env, sha, state="pending")
    with pytest.raises(BridgeError, match="not 'approved'"):
        _mod.PyrevitBridgeModule().run_pyrevit_script(_sid(env), sha, pid, workspace=env["ws"], tool_executor=lambda *a: {})


def test_run_refuses_hash_mismatch(env):
    sha = hashlib.sha256(WRITE_SCRIPT.encode()).hexdigest()
    pid = _approved_plan(env, sha)
    env["script"].write_bytes((WRITE_SCRIPT + "doc.Delete(2)\n").encode("utf-8"))
    calls = []
    with pytest.raises(BridgeError, match="SHA-256 mismatch"):
        _mod.PyrevitBridgeModule().run_pyrevit_script(
            _sid(env), sha, pid, workspace=env["ws"], tool_executor=lambda *a: calls.append(a))
    assert calls == []


def test_run_refuses_hash_not_in_plan(env):
    sha = hashlib.sha256(WRITE_SCRIPT.encode()).hexdigest()
    pid = _approved_plan(env, sha)
    with pytest.raises(BridgeError, match="does not contain"):
        _mod.PyrevitBridgeModule().run_pyrevit_script(
            _sid(env), "0" * 64, pid, workspace=env["ws"], tool_executor=lambda *a: {})


def test_run_approved_calls_bridge_with_verified_source(env):
    sha = hashlib.sha256(WRITE_SCRIPT.encode()).hexdigest()
    pid = _approved_plan(env, sha)
    calls = []
    res = _mod.PyrevitBridgeModule().run_pyrevit_script(
        _sid(env), sha, pid, workspace=env["ws"],
        tool_executor=lambda name, args: calls.append((name, args)) or {"ok": True})
    assert res["status"] == "executed"
    assert calls[0][0] == "revit_run_pyrevit_script"
    assert calls[0][1]["script_source"] == WRITE_SCRIPT
    assert calls[0][1]["script_sha256"] == sha


def test_run_reports_bridge_unavailable(env):
    sha = hashlib.sha256(WRITE_SCRIPT.encode()).hexdigest()
    pid = _approved_plan(env, sha)

    def boom(name, args):
        raise BridgeError("Recipe step tool 'revit_run_pyrevit_script' not found in registry")

    res = _mod.PyrevitBridgeModule().run_pyrevit_script(
        _sid(env), sha, pid, workspace=env["ws"], tool_executor=boom)
    assert res["status"] == "bridge_unavailable"
    assert res["executed"] is False
    assert res["required_bridge_call"] == "revit.run_pyrevit_script"
