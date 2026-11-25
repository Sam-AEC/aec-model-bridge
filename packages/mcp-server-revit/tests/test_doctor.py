import json
import os
import sys

import pytest

from revit_mcp_server import doctor
from revit_mcp_server.doctor import FAIL, NA, OK, WARN

TOKEN = "tok-SECRET-1234567890"


def _env(tmp_path, **extra):
    env = {"MCP_REVIT_MODE": "mock", "MCP_REVIT_WORKSPACE_DIR": str(tmp_path / "ws"),
           "PATH": os.environ.get("PATH", ""), "LOCALAPPDATA": str(tmp_path / "local"),
           "APPDATA": str(tmp_path / "roaming")}
    env.update(extra)
    return env


def _run(tmp_path, platform="linux", **extra):
    (tmp_path / "ws").mkdir(exist_ok=True)
    checks = doctor.run_checks(env=_env(tmp_path, **extra), platform=platform, home=tmp_path / "home",
                               cwd=tmp_path / "cwd", probe=lambda h, p, t: False, pid_alive=lambda pid: True)
    return {c.name: c for c in checks}, checks


def test_clean_mock_setup_has_no_failures(tmp_path):
    by_name, checks = _run(tmp_path)
    assert not [c for c in checks if c.status == FAIL]
    assert by_name["python"].status == OK
    assert by_name["mode"].status == OK and "mock" in by_name["mode"].detail
    assert by_name["workspace"].status == OK
    assert by_name["add-in discovery"].status == NA
    assert by_name["bridge port"].status == NA
    assert by_name["client configs"].status == NA


def test_old_python_fails():
    assert doctor.check_python((3, 9, 1)).status == FAIL
    assert doctor.check_python((3, 12, 0)).status == OK


def test_version_mismatch_warns(tmp_path):
    vf = tmp_path / "VERSION"
    vf.write_text("9.9.9\n")
    assert doctor.check_version("1.5.0", vf).status == WARN
    assert doctor.check_version("9.9.9", vf).status == OK
    assert doctor.check_version("0+unknown", vf).status == WARN


def test_invalid_settings_fail(tmp_path):
    by_name, _ = _run(tmp_path, MCP_REVIT_MODE="nonsense")
    assert by_name["mode"].status == FAIL
    assert "workspace" not in by_name


def test_workspace_missing_warns_and_file_fails(tmp_path):
    env = _env(tmp_path, MCP_REVIT_WORKSPACE_DIR=str(tmp_path / "new" / "ws"))
    by_name = {c.name: c for c in doctor.run_checks(env=env, platform="linux", home=tmp_path, cwd=tmp_path)}
    assert by_name["workspace"].status == WARN
    assert not (tmp_path / "new").exists()  # doctor creates nothing
    afile = tmp_path / "afile"
    afile.write_text("x")
    env = _env(tmp_path, MCP_REVIT_WORKSPACE_DIR=str(afile))
    by_name = {c.name: c for c in doctor.run_checks(env=env, platform="linux", home=tmp_path, cwd=tmp_path)}
    assert by_name["workspace"].status == FAIL


def test_unwritable_workspace_fails(tmp_path, monkeypatch):
    """Simulated, so it also runs as root: the writability probe raises PermissionError."""
    ws = tmp_path / "ws"
    ws.mkdir()

    def denied(*args, **kwargs):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(doctor.tempfile, "NamedTemporaryFile", denied)
    by_name, _ = _run(tmp_path)
    assert by_name["workspace"].status == FAIL
    assert "is not writable: Permission denied" in by_name["workspace"].detail


def test_workspace_that_cannot_be_created_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.os, "access", lambda *a, **k: False)
    env = _env(tmp_path, MCP_REVIT_WORKSPACE_DIR=str(tmp_path / "new" / "ws"))
    by_name = {c.name: c for c in doctor.run_checks(env=env, platform="linux", home=tmp_path, cwd=tmp_path)}
    assert by_name["workspace"].status == FAIL
    assert "cannot be created (no write access to" in by_name["workspace"].detail


def _registry(tmp_path, token=TOKEN, pid=None):
    folder = tmp_path / "local" / "AECModelBridge" / "registry"
    folder.mkdir(parents=True)
    entry = {"provider_id": "revit", "endpoint": "http://127.0.0.1:59999", "pid": pid or os.getpid(),
             "host_version": "2025", "connector_version": "1", "protocol_version": 2,
             "capability_digest": "x", "session_token": token, "started_at": "2026-11-01T10:00:00Z"}
    (folder / "revit-1.json").write_text(json.dumps(entry))
    return folder / "revit-1.json"


def test_addin_discovery_on_windows_never_prints_token(tmp_path):
    entry = _registry(tmp_path)
    before = entry.read_text()
    by_name, checks = _run(tmp_path, platform="win32")
    assert by_name["add-in discovery"].status == OK
    assert "token present" in by_name["add-in discovery"].detail
    assert TOKEN not in doctor.render_table(checks)
    assert TOKEN not in json.dumps([c.__dict__ for c in checks])
    assert entry.read_text() == before  # not pruned or changed
    assert by_name["bridge port"].status == WARN  # mock mode, nothing listening


def test_addin_missing_token_fails_and_port_in_bridge_mode(tmp_path):
    _registry(tmp_path, token="")
    by_name, _ = _run(tmp_path, platform="win32")
    assert by_name["add-in discovery"].status == FAIL
    by_name, _ = _run(tmp_path, platform="win32", MCP_REVIT_MODE="bridge")
    assert by_name["bridge port"].status == FAIL


def test_bridge_port_reachable_uses_probe(tmp_path):
    (tmp_path / "ws").mkdir()
    env = _env(tmp_path, MCP_REVIT_BRIDGE_URL="http://127.0.0.1:4321")
    seen = []
    checks = doctor.run_checks(env=env, platform="linux", home=tmp_path, cwd=tmp_path,
                               probe=lambda h, p, t: seen.append((h, p, t)) or True)
    port = {c.name: c for c in checks}["bridge port"]
    assert port.status == OK and seen == [("127.0.0.1", 4321, doctor.PORT_TIMEOUT)]


def test_client_config_exe_launcher_fails(tmp_path):
    cfg = tmp_path / "roaming" / "Claude"
    cfg.mkdir(parents=True)
    exe = "C:\\Users\\x\\AppData\\Local\\Programs\\Python\\Python312\\Scripts\\aec-model-bridge.exe"
    (cfg / "claude_desktop_config.json").write_text(json.dumps(
        {"mcpServers": {"aec-model-bridge": {"command": exe, "env": {"API_KEY": "sk-should-not-print"}}}}))
    by_name, checks = _run(tmp_path, platform="win32")
    check = by_name["client: Claude Desktop"]
    assert check.status == FAIL and "#159" in check.detail
    assert "sk-should-not-print" not in doctor.render_table(checks)


def test_client_config_valid_and_missing_commands(tmp_path):
    home = tmp_path / "home"
    (home / ".cursor").mkdir(parents=True)
    good = sys.executable
    (home / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": {
        "aec-model-bridge": {"command": good, "args": ["-m", "revit_mcp_server"]},
        "other": {"command": "does-not-matter"},
    }}))
    (home / ".claude.json").write_text(json.dumps({"projects": {"/p": {"mcpServers": {
        "bridge": {"command": "definitely-not-installed-xyz", "args": ["revit-mcp-server"]}}}}}))
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text('[mcp_servers.aec]\ncommand = "uvx"\nargs = ["aec-model-bridge"]\n')
    by_name, checks = _run(tmp_path)
    assert by_name["client: Cursor"].status == OK
    assert by_name["client: Claude Code"].status == FAIL
    assert "other" not in " ".join(c.detail for c in checks)
    codex = by_name["client: Codex"]
    assert codex.status in (OK, FAIL)  # depends on uvx being installed here


def test_unparseable_client_config_warns(tmp_path):
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / ".claude.json").write_text("{not json")
    by_name, _ = _run(tmp_path)
    assert by_name["client: Claude Code"].status == WARN


def test_main_json_and_exit_codes(tmp_path, monkeypatch, capsys):
    (tmp_path / "ws").mkdir()
    for key, value in _env(tmp_path).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(doctor.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    assert doctor.main(["--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True and {c["name"] for c in data["checks"]} >= {"python", "version", "mode", "workspace"}
    assert doctor.main([]) == 0
    assert "CHECK" in capsys.readouterr().out
    monkeypatch.setenv("MCP_REVIT_MODE", "nonsense")
    assert doctor.main([]) == 1


def test_doctor_subcommand_routes_from_entry_point(monkeypatch):
    from revit_mcp_server import mcp_server

    monkeypatch.setattr(sys, "argv", ["aec-model-bridge", "doctor", "--json"])
    monkeypatch.setattr(doctor, "main", lambda argv: 7)
    with pytest.raises(SystemExit) as exc:
        mcp_server.run_mcp_server()
    assert exc.value.code == 7


def test_venv_interpreter_in_scripts_is_not_a_launcher():
    venv_python = "C:\\work\\proj\\.venv\\Scripts\\python.exe"
    assert not doctor._scripts_exe(venv_python)
    assert not doctor._scripts_exe(venv_python.replace("python.exe", "pythonw.exe"))
    assert doctor._scripts_exe("C:\\Python312\\Scripts\\aec-model-bridge.exe")


# ---- --fix ------------------------------------------------------------------

def _plan(tmp_path, platform="linux", pid_alive=lambda pid: True, python=sys.executable, **extra):
    return doctor.plan_fixes(env=_env(tmp_path, **extra), platform=platform, home=tmp_path / "home",
                             cwd=tmp_path / "cwd", pid_alive=pid_alive, python=python)


def test_clean_setup_plans_no_fixes(tmp_path):
    (tmp_path / "ws").mkdir()
    assert _plan(tmp_path) == []
    assert doctor.apply_fixes([]) == []


def test_fix_creates_missing_workspace(tmp_path):
    ws = tmp_path / "new" / "ws"
    fixes = _plan(tmp_path, MCP_REVIT_WORKSPACE_DIR=str(ws))
    assert [f.check for f in fixes] == ["workspace"]
    assert not ws.exists()  # planning changes nothing
    [result] = doctor.apply_fixes(fixes)
    assert result["status"] == "applied" and ws.is_dir()
    assert _plan(tmp_path, MCP_REVIT_WORKSPACE_DIR=str(ws)) == []


def test_no_fix_for_workspace_that_is_a_file(tmp_path):
    afile = tmp_path / "afile"
    afile.write_text("keep me")
    assert _plan(tmp_path, MCP_REVIT_WORKSPACE_DIR=str(afile)) == []
    assert afile.read_text() == "keep me"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_fix_restores_owner_permissions_on_workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "data.json").write_text("{}")
    ws.chmod(0o500)
    try:
        [fix] = _plan(tmp_path)
        assert fix.check == "workspace" and "0500 -> 0700" in fix.action
        assert doctor.apply_fixes([fix])[0]["status"] == "applied"
        assert ws.stat().st_mode & 0o777 == 0o700
        assert (ws / "data.json").read_text() == "{}"  # contents untouched
    finally:
        ws.chmod(0o700)


def test_fix_deletes_only_stale_registry_files(tmp_path):
    (tmp_path / "ws").mkdir()
    entry = _registry(tmp_path, pid=111)
    live = entry.with_name("revit-2.json")
    live.write_text(entry.read_text().replace('"pid": 111', '"pid": 222'))
    broken = entry.with_name("revit-3.json")
    broken.write_text("{not json")

    def alive(pid):
        return pid == 222

    assert _plan(tmp_path, platform="linux", pid_alive=alive) == []  # the registry is Windows only
    fixes = _plan(tmp_path, platform="win32", pid_alive=alive)
    assert [f.check for f in fixes] == ["add-in discovery"] and "revit-1.json" in fixes[0].action
    assert TOKEN not in fixes[0].action
    [result] = doctor.apply_fixes(fixes)
    assert result["status"] == "applied"
    assert not entry.exists() and live.exists() and broken.exists()


def test_registry_fix_rechecks_before_deleting(tmp_path):
    (tmp_path / "ws").mkdir()
    entry = _registry(tmp_path, pid=111)
    state = {"alive": False}
    fixes = _plan(tmp_path, platform="win32", pid_alive=lambda pid: state["alive"])
    state["alive"] = True  # the process is running again between plan and apply
    [result] = doctor.apply_fixes(fixes)
    assert result["status"] == "skipped" and entry.exists()


def _cursor_config(tmp_path, entry):
    folder = tmp_path / "home" / ".cursor"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "mcp.json"
    path.write_text(json.dumps({"theme": "dark", "mcpServers": {"aec-model-bridge": entry,
                                                                "other": {"command": "nope-xyz"}}}))
    return path


def test_fix_rewrites_broken_client_entry_with_backup(tmp_path):
    (tmp_path / "ws").mkdir()
    env_block = {"MCP_REVIT_MODE": "bridge", "MCP_REVIT_APPROVAL_MODE": "strict", "API_KEY": "sk-keep"}
    path = _cursor_config(tmp_path, {"type": "stdio", "command": "definitely-not-installed-xyz", "args": ["x"],
                                     "env": env_block})
    original = path.read_text()
    fixes = _plan(tmp_path)
    assert [f.check for f in fixes] == ["client: Cursor"]
    assert path.read_text() == original  # planning changes nothing
    assert "sk-keep" not in fixes[0].action
    [result] = doctor.apply_fixes(fixes)
    assert result["status"] == "applied" and "sk-keep" not in result["result"]
    data = json.loads(path.read_text())
    entry = data["mcpServers"]["aec-model-bridge"]
    assert entry["command"] == sys.executable and entry["args"] == ["-m", "revit_mcp_server"]
    assert entry["env"] == env_block and entry["type"] == "stdio"  # env and approval settings untouched
    assert data["theme"] == "dark" and data["mcpServers"]["other"] == {"command": "nope-xyz"}
    backups = list(path.parent.glob("mcp.json.aec-backup-*"))
    assert len(backups) == 1 and backups[0].read_text() == original
    assert not list(path.parent.glob("*.aec-tmp"))
    by_name, _ = _run(tmp_path)
    assert by_name["client: Cursor"].status == OK
    assert _plan(tmp_path) == []


def test_fix_rewrites_exe_launcher_nested_in_claude_code_config(tmp_path):
    (tmp_path / "ws").mkdir()
    home = tmp_path / "home"
    home.mkdir()
    exe = "C:\\Python312\\Scripts\\aec-model-bridge.exe"
    (home / ".claude.json").write_text(json.dumps({"projects": {"/p": {"mcpServers": {"aec": {"command": exe}}}}}))
    [fix] = _plan(tmp_path)
    assert doctor.apply_fixes([fix])[0]["status"] == "applied"
    entry = json.loads((home / ".claude.json").read_text())["projects"]["/p"]["mcpServers"]["aec"]
    assert entry == {"command": sys.executable, "args": ["-m", "revit_mcp_server"]}


def test_no_fix_for_good_url_or_unparseable_client_entries(tmp_path):
    (tmp_path / "ws").mkdir()
    _cursor_config(tmp_path, {"command": sys.executable, "args": ["-m", "revit_mcp_server"]})
    (tmp_path / "home" / ".claude.json").write_text("{not json")
    (tmp_path / "cwd" / ".vscode").mkdir(parents=True)
    (tmp_path / "cwd" / ".vscode" / "mcp.json").write_text(json.dumps(
        {"servers": {"aec-model-bridge": {"url": "http://127.0.0.1:1"}}}))
    assert _plan(tmp_path) == []
    assert (tmp_path / "home" / ".claude.json").read_text() == "{not json"


def test_codex_toml_is_a_manual_step(tmp_path):
    (tmp_path / "ws").mkdir()
    codex = tmp_path / "home" / ".codex"
    codex.mkdir(parents=True)
    (codex / "config.toml").write_text('[mcp_servers.aec]\ncommand = "not-installed-xyz"\nargs = ["aec-model-bridge"]\n')
    before = (codex / "config.toml").read_text()
    [fix] = _plan(tmp_path)
    assert fix.apply is None
    [result] = doctor.apply_fixes([fix])
    assert result["status"] == "manual" and (codex / "config.toml").read_text() == before


def test_failed_fix_does_not_stop_the_others():
    def boom():
        raise PermissionError(13, "Permission denied")

    results = doctor.apply_fixes([doctor.Fix("a", "first", boom), doctor.Fix("b", "second", lambda: "done")])
    assert [r["status"] for r in results] == ["failed", "applied"]
    assert "Permission denied" in results[0]["result"]


def test_main_report_only_lists_fixes_and_fix_applies_them(tmp_path, monkeypatch, capsys):
    ws = tmp_path / "missing-ws"
    for key, value in _env(tmp_path, MCP_REVIT_WORKSPACE_DIR=str(ws)).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(doctor.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    assert doctor.main([]) == 0
    out = capsys.readouterr().out
    assert "Fixes available" in out and "--fix" in out and not ws.exists()
    assert doctor.main(["--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["fixes_applied"] is False and data["fixes"][0]["status"] == "available" and not ws.exists()
    assert doctor.main(["--fix"]) == 0
    assert "APPLIED" in capsys.readouterr().out and ws.is_dir()
    assert doctor.main(["--fix", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["fixes_applied"] is True and data["fixes"] == []
