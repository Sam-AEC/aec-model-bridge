"""``aec-model-bridge doctor``: a check of the local setup, read-only by default.

Prints a plain table (or JSON with ``--json``) and exits 1 when any check FAILs. Without
``--fix`` it changes nothing and only lists the fixes it could apply. It reports whether a
session token is present and never prints its value, and it never prints environment
values found in client config files (they can hold keys).

``--fix`` applies local fixes for faults the checks found, printing each one:

* create a missing workspace folder;
* restore owner read/write/search permission on a workspace folder this user owns;
* delete add-in registry files whose Revit process is no longer running (the same rule
  the server's own discovery uses; a file for a running process is never touched);
* point a client config entry that FAILs (an ``.exe`` launcher, issue #159, or a missing
  command) at this Python: ``<python> -m revit_mcp_server``. The old file is kept as
  ``<name>.aec-backup-<timestamp>``; ``env`` and every other key are kept as they are.

It never starts or contacts Revit, never deletes user data and never changes approval
settings. Codex (TOML) entries are reported for a manual edit.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse

OK, WARN, FAIL, NA = "OK", "WARN", "FAIL", "N/A"
MIN_PYTHON = (3, 11)
PORT_TIMEOUT = 1.0
SERVER_MARKERS = ("aec-model-bridge", "aec_model_bridge", "revit-mcp-server", "revit_mcp_server")
OPTIONAL_PACKAGES = ("anthropic", "specklepy", "networkx", "openpyxl", "yaml")


@dataclass
class Check:
    name: str
    status: str
    detail: str


@dataclass
class Fix:
    """A local fix for a FAIL or WARN check. ``apply`` is None for a manual step."""

    check: str
    action: str
    apply: Callable[[], str] | None = field(default=None, repr=False, compare=False)


def _version_file() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "VERSION"
        if candidate.is_file() and (parent / "docs").is_dir():
            return candidate
    return None


def check_python(version_info: Sequence[int] = tuple(sys.version_info[:3])) -> Check:
    text = ".".join(str(n) for n in version_info[:3])
    if tuple(version_info[:2]) < MIN_PYTHON:
        return Check("python", FAIL, f"Python {text}; this server needs {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer.")
    return Check("python", OK, f"Python {text}")


def check_version(installed: str | None = None, version_file: Path | None = None) -> Check:
    if installed is None:
        from . import __version__ as installed
    path = version_file if version_file is not None else _version_file()
    if installed.startswith("0+unknown"):
        return Check("version", WARN, "The package is not installed (running from a source tree); no installed version to compare.")
    if path is None:
        return Check("version", OK, f"{installed} (no VERSION file next to this install to compare with)")
    try:
        wanted = path.read_text(encoding="utf-8").strip()
    except OSError:
        return Check("version", WARN, f"{installed}; could not read {path.name}.")
    if wanted != installed:
        return Check("version", WARN, f"Installed package is {installed} but VERSION says {wanted}. Reinstall or sync the checkout.")
    return Check("version", OK, installed)


def _load_config(env: Mapping[str, str]):
    """A fresh Config built from ``env`` (the module-level one was built at import)."""
    from .config import Config

    saved = dict(os.environ)
    try:
        for key in [k for k in os.environ if k.upper().startswith("MCP_REVIT_")]:
            del os.environ[key]
        os.environ.update({k: v for k, v in env.items() if k.upper().startswith("MCP_REVIT_")})
        return Config()
    finally:
        os.environ.clear()
        os.environ.update(saved)


def check_mode(cfg: Any, error: str | None) -> Check:
    if error:
        return Check("mode", FAIL, f"MCP_REVIT_* settings are invalid: {error}")
    return Check("mode", OK, f"{cfg.mode.value}; approvals: {cfg.approval_mode}")


def check_policy(cfg: Any, env: Mapping[str, str]) -> Check:
    """Active policy files (machine and workspace), their hashes, tiers that are off, Dev override."""
    from .security import policy as pol
    from .security.dev_mode import active_dev

    saved = dict(os.environ)
    try:
        for key in [k for k in os.environ if k.upper() in (pol.POLICY_ENV, pol.MACHINE_POLICY_ENV, "PROGRAMDATA")]:
            del os.environ[key]
        os.environ.update({k: v for k, v in env.items() if k.upper() in (pol.POLICY_ENV, pol.MACHINE_POLICY_ENV, "PROGRAMDATA")})
        try:
            policy = pol.load_policy(Path(cfg.workspace_dir))
        except pol.PolicyError as exc:
            return Check("policy", FAIL, f"{exc}")
    finally:
        os.environ.clear()
        os.environ.update(saved)
    try:
        dev = active_dev(Path(cfg.workspace_dir))
    except Exception:  # noqa: BLE001 - reporting only
        dev = False
    if not policy.layers:
        files = "no policy file"
    else:
        files = "; ".join(f"{lay.level}: {lay.source} ({lay.hash})" for lay in policy.layers)
    off = pol.tiers_off(policy)
    tiers = ", ".join(f"{t} (off in {src})" for t, src in sorted(off.items())) or "none"
    override = "Dev mode override is ACTIVE: policy limits are lifted and audited" if dev else "Dev mode override is not active"
    return Check("policy", WARN if dev else OK, f"{files}; tiers off: {tiers}; {override}")


def check_workspace(cfg: Any) -> Check:
    path = Path(cfg.workspace_dir)
    if not path.exists():
        parent = path.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        if os.access(parent, os.W_OK):
            return Check("workspace", WARN, f"{path} does not exist yet; it is created on first run.")
        return Check("workspace", FAIL, f"{path} does not exist and cannot be created (no write access to {parent}).")
    if not path.is_dir():
        return Check("workspace", FAIL, f"{path} is not a folder.")
    try:
        with tempfile.NamedTemporaryFile(dir=path, prefix=".doctor-", delete=True):
            pass
    except OSError as exc:
        return Check("workspace", FAIL, f"{path} is not writable: {exc.strerror or exc}")
    return Check("workspace", OK, f"{path} exists and is writable")


def _registry_dir(env: Mapping[str, str]) -> Path | None:
    base = env.get("LOCALAPPDATA")
    return Path(base) / "AECModelBridge" / "registry" if base else None


def read_registry(env: Mapping[str, str], pid_alive=None) -> tuple[list[dict[str, Any]], str | None]:
    """Registry entries as plain facts (no token value). Does not prune anything."""
    folder = _registry_dir(env)
    if folder is None or not folder.is_dir():
        return [], None
    if pid_alive is None:
        from .bridge.discovery import is_pid_alive as pid_alive

    rows: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            rows.append({"file": path.name, "valid": False})
            continue
        if not isinstance(data, dict):
            rows.append({"file": path.name, "valid": False})
            continue
        pid = data.get("pid")
        rows.append({
            "file": path.name, "valid": True, "provider": data.get("provider_id"),
            "endpoint": data.get("endpoint"), "pid": pid,
            "alive": bool(isinstance(pid, int) and pid_alive(pid)),
            "token_present": bool(data.get("session_token")),
        })
    return rows, str(folder)


def check_addin(env: Mapping[str, str], platform: str, mode: str, rows: list[dict[str, Any]]) -> Check:
    if platform != "win32":
        return Check("add-in discovery", NA, "The Revit add-in is Windows only; not applicable on this system.")
    if _registry_dir(env) is None:
        return Check("add-in discovery", WARN, "LOCALAPPDATA is not set, so the add-in registry cannot be found.")
    if not rows:
        status = WARN if mode == "bridge" else OK
        return Check("add-in discovery", status, "No add-in registry entry found. Start Revit with the AEC Bridge add-in installed"
                     + ("." if mode == "bridge" else " (not needed in mock mode)."))
    live = [r for r in rows if r.get("valid") and r.get("alive")]
    if not live:
        return Check("add-in discovery", WARN, f"{len(rows)} registry entr{'y' if len(rows) == 1 else 'ies'}, none for a running Revit (stale or unreadable).")
    missing = [r["file"] for r in live if not r.get("token_present")]
    if missing:
        return Check("add-in discovery", FAIL, f"Registry entry without a session token: {', '.join(missing)}.")
    return Check("add-in discovery", OK, f"{len(live)} running Revit instance(s); session token present (value not shown).")


def _port_open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_bridge_port(cfg: Any, rows: list[dict[str, Any]], timeout: float = PORT_TIMEOUT, probe=_port_open) -> Check:
    endpoints = [cfg.bridge_url] if cfg.bridge_url else [r["endpoint"] for r in rows if r.get("alive") and r.get("endpoint")]
    if not endpoints:
        return Check("bridge port", NA, "No bridge endpoint configured or discovered.")
    results = []
    for endpoint in endpoints:
        parsed = urlparse(str(endpoint))
        host, port = parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
        if not host:
            results.append((endpoint, False))
            continue
        results.append((f"{host}:{port}", probe(host, port, timeout)))
    bad = [name for name, ok in results if not ok]
    if bad:
        status = FAIL if cfg.mode.value == "bridge" else WARN
        return Check("bridge port", status, f"Not reachable: {', '.join(bad)}.")
    return Check("bridge port", OK, f"Reachable: {', '.join(name for name, _ in results)}")


def check_ifcopenshell() -> Check:
    try:
        import ifcopenshell  # noqa: F401
    except Exception as exc:  # ImportError or a broken native library
        return Check("ifcopenshell", WARN, f"Import failed ({type(exc).__name__}); IFC tools will not work.")
    return Check("ifcopenshell", OK, f"imported {getattr(ifcopenshell, 'version', '')}".strip())


def check_optional_packages() -> Check:
    missing = [name for name in OPTIONAL_PACKAGES if importlib.util.find_spec(name) is None]
    if missing:
        return Check("optional packages", WARN, f"Not installed: {', '.join(missing)}. Related tools are unavailable.")
    return Check("optional packages", OK, ", ".join(OPTIONAL_PACKAGES))


# ---- MCP client configs ---------------------------------------------------

def client_config_files(env: Mapping[str, str], home: Path, cwd: Path, platform: str) -> list[tuple[str, Path]]:
    if platform == "win32":
        appdata = Path(env["APPDATA"]) if env.get("APPDATA") else home / "AppData" / "Roaming"
        desktop = appdata / "Claude" / "claude_desktop_config.json"
    elif platform == "darwin":
        desktop = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    else:
        desktop = home / ".config" / "Claude" / "claude_desktop_config.json"
    return [
        ("Claude Desktop", desktop),
        ("Claude Code", home / ".claude.json"),
        ("Claude Code (project)", cwd / ".mcp.json"),
        ("Cursor", home / ".cursor" / "mcp.json"),
        ("Windsurf", home / ".codeium" / "windsurf" / "mcp_config.json"),
        ("VS Code (project)", cwd / ".vscode" / "mcp.json"),
        ("Gemini CLI", home / ".gemini" / "settings.json"),
        ("Codex", home / ".codex" / "config.toml"),
    ]


def _servers(data: Any) -> dict[str, dict]:
    """Every server table named mcpServers / servers / mcp_servers anywhere in the document."""
    found: dict[str, dict] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("mcpServers", "servers", "mcp_servers") and isinstance(value, dict):
                    for name, entry in value.items():
                        if isinstance(entry, dict):
                            found.setdefault(str(name), entry)
                elif isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return found


def _is_ours(name: str, entry: dict) -> bool:
    haystack = " ".join([name, str(entry.get("command", "")), *[str(a) for a in entry.get("args", []) if isinstance(a, str)]]).lower()
    return any(marker in haystack for marker in SERVER_MARKERS)


def _scripts_exe(command: str) -> bool:
    norm = command.replace("\\", "/").lower()
    # A venv keeps its interpreter in Scripts (python.exe, pythonw.exe); only the
    # pip-generated console-script launchers are the #159 problem.
    if re.fullmatch(r"pythonw?(\d+(\.\d+)?)?\.exe", norm.rsplit("/", 1)[-1]):
        return False
    return norm.endswith(".exe") and "/scripts/" in norm and "python" in norm


def judge_command(command: Any, path_env: str | None) -> tuple[str, str]:
    if not isinstance(command, str) or not command.strip():
        return FAIL, "has no command (a url-based server is not checked here)"
    command = command.strip()
    if _scripts_exe(command):
        return FAIL, (f"command '{command}' is an .exe launcher under python\\Scripts (issue #159). "
                      "Use `uvx` (see docs/install.md) or `python -m revit_mcp_server` with the full path to python.exe.")
    if "/" in command or "\\" in command:
        if Path(command).is_file():
            return OK, f"command '{command}' exists"
        if "\\" in command and os.name != "nt":
            return WARN, f"command '{command}' is a Windows path; it cannot be checked on this system"
        return FAIL, f"command '{command}' does not exist"
    if shutil.which(command, path=path_env):
        return OK, f"command '{command}' found on PATH"
    return FAIL, f"command '{command}' was not found on PATH"


def check_client_configs(env: Mapping[str, str], home: Path, cwd: Path, platform: str) -> list[Check]:
    checks: list[Check] = []
    seen = False
    for client, path in client_config_files(env, home, cwd, platform):
        if not path.is_file():
            continue
        try:
            if path.suffix == ".toml":
                import tomllib

                data = tomllib.loads(path.read_text(encoding="utf-8"))
            else:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            checks.append(Check(f"client: {client}", WARN, f"{path} could not be parsed."))
            continue
        ours = {n: e for n, e in _servers(data).items() if _is_ours(n, e)}
        if not ours:
            continue
        seen = True
        for name, entry in ours.items():
            status, detail = judge_command(entry.get("command"), env.get("PATH"))
            checks.append(Check(f"client: {client}", status, f"{path} [{name}]: {detail}"))
    if not seen and not checks:
        checks.append(Check("client configs", NA, "No known MCP client config with an AEC Model Bridge entry was found."))
    return checks


# ---- fixes ----------------------------------------------------------------

FIX_ARGS = ["-m", "revit_mcp_server"]


def _workspace_fixes(cfg: Any, platform: str) -> list[Fix]:
    path = Path(cfg.workspace_dir)
    if not path.exists():
        if check_workspace(cfg).status != WARN:
            return []  # cannot be created; a fix would only fail

        def create() -> str:
            path.mkdir(parents=True, exist_ok=True)
            return f"created {path}"

        return [Fix("workspace", f"create the workspace folder {path}", create)]
    if platform == "win32" or os.name == "nt" or path.is_symlink() or not path.is_dir():
        return []
    st = path.stat()
    if st.st_uid != os.getuid() or (st.st_mode & 0o700) == 0o700:
        return []
    mode = st.st_mode & 0o7777
    wanted = mode | 0o700

    def chmod() -> str:
        os.chmod(path, wanted)
        return f"{path} mode {mode:04o} -> {wanted:04o}"

    return [Fix("workspace", f"give the owner read/write/search access to {path} (mode {mode:04o} -> {wanted:04o})", chmod)]


def _registry_fixes(env: Mapping[str, str], pid_alive) -> list[Fix]:
    folder = _registry_dir(env)
    if folder is None or not folder.is_dir():
        return []
    if pid_alive is None:
        from .bridge.discovery import is_pid_alive as pid_alive
    rows, _ = read_registry(env, pid_alive)
    fixes = []
    for row in rows:
        if not row.get("valid") or row.get("alive") or not isinstance(row.get("pid"), int):
            continue  # unreadable files are left for a person to look at
        path, pid = folder / row["file"], row["pid"]

        def delete(path: Path = path, pid: int = pid) -> str:
            try:
                current = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                return f"skipped {path.name}: it changed or could not be read again"
            if not isinstance(current, dict) or current.get("pid") != pid or pid_alive(pid):
                return f"skipped {path.name}: its process is running or the file changed"
            path.unlink()
            return f"deleted {path.name}"

        fixes.append(Fix("add-in discovery", f"delete stale registry file {path.name} (process {pid} is not running)", delete))
    return fixes


def _write_json_with_backup(path: Path, data: Any) -> Path:
    """Copy ``path`` to a timestamped backup, then replace it in one step (temp file + rename)."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.aec-backup-{stamp}")
    n = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.aec-backup-{stamp}-{n}")
        n += 1
    shutil.copy2(path, backup)
    tmp = path.with_name(f"{path.name}.aec-tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return backup


def _read_client_config(path: Path) -> Any:
    if path.suffix == ".toml":
        import tomllib

        return tomllib.loads(path.read_text(encoding="utf-8"))
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _client_fixes(env: Mapping[str, str], home: Path, cwd: Path, platform: str, python: str) -> list[Fix]:
    fixes: list[Fix] = []
    path_env = env.get("PATH")

    def broken_names(data: Any) -> list[str]:
        return [name for name, entry in _servers(data).items()
                if _is_ours(name, entry) and isinstance(entry.get("command"), str) and entry["command"].strip()
                and judge_command(entry["command"], path_env)[0] == FAIL]

    for client, path in client_config_files(env, home, cwd, platform):
        if not path.is_file():
            continue
        try:
            broken = broken_names(_read_client_config(path))
        except Exception:
            continue  # never rewrite a file that cannot be parsed
        if not broken:
            continue
        if path.suffix == ".toml":
            fixes.append(Fix(f"client: {client}", f"edit {path} by hand: set command = \"{python}\" and "
                             f"args = {json.dumps(FIX_ARGS)} for {', '.join(broken)}"))
            continue

        def rewrite(path: Path = path) -> str:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            servers = _servers(data)  # the entries are the dicts inside ``data``
            changed = broken_names(data)
            if not changed:
                return f"skipped {path}: nothing to change any more"
            for name in changed:
                servers[name]["command"] = python
                servers[name]["args"] = list(FIX_ARGS)
            backup = _write_json_with_backup(path, data)
            return f"updated {', '.join(changed)} in {path}; backup {backup.name}"

        fixes.append(Fix(f"client: {client}", f"point {', '.join(broken)} in {path} at {python} {' '.join(FIX_ARGS)} "
                         "(backup kept, env unchanged)", rewrite))
    return fixes


def plan_fixes(env: Mapping[str, str] | None = None, platform: str | None = None,
               home: Path | None = None, cwd: Path | None = None,
               pid_alive=None, python: str | None = None) -> list[Fix]:
    """The fixes ``--fix`` would apply. Planning changes nothing."""
    env = dict(os.environ) if env is None else dict(env)
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else home
    cwd = Path.cwd() if cwd is None else cwd
    python = sys.executable if python is None else python

    fixes: list[Fix] = []
    try:
        cfg = _load_config(env)
    except Exception:
        cfg = None  # invalid settings are for a person to correct
    if cfg is not None:
        fixes += _workspace_fixes(cfg, platform)
    if platform == "win32":
        fixes += _registry_fixes(env, pid_alive)
    if python and Path(python).is_file():
        fixes += _client_fixes(env, home, cwd, platform, python)
    return fixes


def apply_fixes(fixes: list[Fix]) -> list[dict[str, str]]:
    """Apply each fix in order. One failure does not stop the others."""
    results = []
    for fix in fixes:
        if fix.apply is None:
            status, result = "manual", "manual step; not applied"
        else:
            try:
                result = fix.apply()
                status = "skipped" if result.startswith("skipped") else "applied"
            except (OSError, ValueError) as exc:
                status, result = "failed", f"failed: {getattr(exc, 'strerror', None) or exc}"
        results.append({"check": fix.check, "action": fix.action, "status": status, "result": result})
    return results


# ---- run ------------------------------------------------------------------

def run_checks(env: Mapping[str, str] | None = None, platform: str | None = None,
               home: Path | None = None, cwd: Path | None = None,
               probe=_port_open, pid_alive=None) -> list[Check]:
    env = dict(os.environ) if env is None else dict(env)
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else home
    cwd = Path.cwd() if cwd is None else cwd

    checks = [check_python(), check_version()]
    cfg, error = None, None
    try:
        cfg = _load_config(env)
    except Exception as exc:
        error = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
    checks.append(check_mode(cfg, error))
    if cfg is not None:
        rows, _folder = read_registry(env, pid_alive) if platform == "win32" else ([], None)
        checks.append(check_workspace(cfg))
        checks.append(check_policy(cfg, env))
        checks.append(check_addin(env, platform, cfg.mode.value, rows))
        checks.append(check_bridge_port(cfg, rows, probe=probe))
    checks += [check_ifcopenshell(), check_optional_packages()]
    checks += check_client_configs(env, home, cwd, platform)
    return checks


def render_table(checks: list[Check]) -> str:
    width = max(len(c.name) for c in checks)
    lines = [f"{'CHECK'.ljust(width)}  STATUS  DETAIL", f"{'-' * width}  ------  ------"]
    lines += [f"{c.name.ljust(width)}  {c.status.ljust(6)}  {c.detail}" for c in checks]
    fails = sum(c.status == FAIL for c in checks)
    warns = sum(c.status == WARN for c in checks)
    lines.append("")
    lines.append(f"{fails} FAIL, {warns} WARN, {len(checks)} checks.")
    return "\n".join(lines)


def render_fixes(results: list[dict[str, str]], applied: bool) -> str:
    if not results:
        return "No fixes to apply." if applied else ""
    if not applied:
        lines = ["Fixes available (run `aec-model-bridge doctor --fix` to apply):"]
        lines += [f"  - [{r['check']}] {r['action']}" for r in results]
    else:
        lines = ["Fixes:"]
        lines += [f"  - [{r['check']}] {r['status'].upper()}: {r['action']}. {r['result']}" for r in results]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aec-model-bridge doctor",
                                     description="Check the local AEC Model Bridge setup. Read-only unless --fix is given.")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    parser.add_argument("--fix", action="store_true",
                        help="apply safe local fixes (workspace folder, stale registry files, broken client entries)")
    args = parser.parse_args(argv)
    from . import __version__

    fixes = plan_fixes()
    if args.fix:
        results = apply_fixes(fixes)
    else:
        results = [{"check": f.check, "action": f.action, "status": "available" if f.apply else "manual", "result": ""}
                   for f in fixes]
    checks = run_checks()  # after any fixes, so the table shows the current state
    failed = any(c.status == FAIL for c in checks)
    if args.json:
        print(json.dumps({"version": __version__, "ok": not failed, "checks": [asdict(c) for c in checks],
                          "fixes_applied": args.fix, "fixes": results}, indent=2))
    else:
        text = render_fixes(results, args.fix)
        if text and args.fix:
            print(text + "\n")
        print(render_table(checks))
        if text and not args.fix:
            print("\n" + text)
    return 1 if failed else 0


def run() -> None:
    sys.exit(main())


if __name__ == "__main__":
    run()
