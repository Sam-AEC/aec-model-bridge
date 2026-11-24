"""``aec-model-bridge doctor``: a read-only check of the local setup.

Prints a plain table (or JSON with ``--json``) and exits 1 when any check FAILs. It never
changes anything: it does not prune registry entries, create the workspace or start
Revit. It reports whether a session token is present and never prints its value, and it
never prints environment values found in client config files (they can hold keys).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import socket
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aec-model-bridge doctor", description="Check the local AEC Model Bridge setup. Read-only.")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = parser.parse_args(argv)
    from . import __version__

    checks = run_checks()
    failed = any(c.status == FAIL for c in checks)
    if args.json:
        print(json.dumps({"version": __version__, "ok": not failed, "checks": [asdict(c) for c in checks]}, indent=2))
    else:
        print(render_table(checks))
    return 1 if failed else 0


def run() -> None:
    sys.exit(main())


if __name__ == "__main__":
    run()
