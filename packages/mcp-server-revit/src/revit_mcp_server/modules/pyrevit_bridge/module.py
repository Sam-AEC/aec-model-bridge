"""
pyrevit_bridge module -- discover and run existing pyRevit scripts behind the approval gate.

Commands:
  list_pyrevit_scripts     -- read-only scan of configured pyRevit extension dirs.
  plan_run_pyrevit_script  -- builds an ActionPlan draft (path, SHA-256, detected write
                              lines). Never executes anything.
  run_pyrevit_script       -- runs a script only for an *approved* plan whose recorded
                              SHA-256 still matches the file on disk.

Extension dirs come from MCP_REVIT_PYREVIT_EXTENSION_DIRS (os.pathsep separated).
Every path is resolved and confined to those dirs.

Execution inside Revit is delegated to the bridge call `revit.run_pyrevit_script`
(tool name `revit_run_pyrevit_script`). That provider tool and the add-in handler do
NOT exist yet: see docs/pyrevit-bridge.md. Until they do, run_pyrevit_script performs
all checks and then reports status "bridge_unavailable" instead of running anything.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from revit_mcp_server.errors import BridgeError, WorkspaceViolation
from revit_mcp_server.security.workspace import WorkspaceMonitor

ENV_VAR = "MCP_REVIT_PYREVIT_EXTENSION_DIRS"
MODULE_ID = "pyrevit_bridge"
RUN_TOOL = f"{MODULE_ID}_run_pyrevit_script"
BRIDGE_TOOL = "revit_run_pyrevit_script"  # provider tool; maps to bridge call revit.run_pyrevit_script
BRIDGE_CALL = "revit.run_pyrevit_script"
MAX_SCRIPT_BYTES = 1_000_000

# Heuristic only: absence of a match does NOT mean a script is read-only.
WRITE_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("Transaction", re.compile(r"\bTransaction(Group)?\b")),
    ("Start", re.compile(r"\.Start\s*\(")),
    ("Commit", re.compile(r"\.Commit\s*\(")),
    ("Delete", re.compile(r"\.Delete\s*\(")),
    ("ElementTransformUtils", re.compile(r"\bElementTransformUtils\b")),
]


def _extension_dirs() -> List[Path]:
    raw = os.environ.get(ENV_VAR, "")
    dirs: List[Path] = []
    for part in raw.split(os.pathsep):
        part = part.strip()
        if part:
            p = Path(part).expanduser()
            if p.is_dir():
                dirs.append(p.resolve())
    return dirs


def detect_write_calls(text: str) -> List[Dict[str, Any]]:
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        kinds = [name for name, pat in WRITE_PATTERNS if pat.search(line)]
        if kinds:
            hits.append({"line": lineno, "kinds": kinds, "text": stripped[:200]})
    return hits


def _docstring(text: str) -> Optional[str]:
    try:
        doc = ast.get_docstring(ast.parse(text))
    except (SyntaxError, ValueError):  # IronPython 2 syntax is common in pyRevit scripts
        m = re.match(r'\s*(?:[rRuU]?)("""|\'\'\')(.*?)\1', text, re.S)
        doc = m.group(2).strip() if m else None
    if not doc:
        return None
    return " ".join(doc.split())[:300]


def _resolve_script(script_id: str, dirs: List[Path]) -> Path:
    """Map '<root index>:<relative path>' to a verified script path. Raises on any violation."""
    if not dirs:
        raise BridgeError(f"No pyRevit extension directories configured; set {ENV_VAR}.")
    if not isinstance(script_id, str) or ":" not in script_id:
        raise BridgeError("Invalid script_id; expected '<index>:<relative path>' from list_pyrevit_scripts.")
    idx_s, rel = script_id.split(":", 1)
    if not idx_s.isdigit() or int(idx_s) >= len(dirs):
        raise BridgeError("Invalid script_id: unknown extension directory index.")
    if "\\" in rel or "\x00" in rel:
        raise BridgeError("Invalid script_id: path traversal rejected.")
    rel_path = PurePosixPath(rel)
    if rel_path.is_absolute() or ".." in rel_path.parts or not rel_path.parts:
        raise BridgeError("Invalid script_id: path traversal rejected.")
    if (
        rel_path.name != "script.py"
        or not rel_path.parent.name.endswith(".pushbutton")
        or not any(part.endswith(".extension") for part in rel_path.parts)
    ):
        raise BridgeError("Invalid script_id: not an <name>.extension/**/<name>.pushbutton/script.py file.")
    root = dirs[int(idx_s)]
    try:
        resolved = WorkspaceMonitor([root]).assert_in_workspace(root.joinpath(*rel_path.parts))
    except WorkspaceViolation as exc:
        raise BridgeError(f"Invalid script_id: path traversal rejected ({exc}).") from exc
    if not resolved.is_file():
        raise BridgeError("pyRevit script not found.")
    return resolved


def _read_script(path: Path) -> Tuple[bytes, str]:
    data = path.read_bytes()
    if len(data) > MAX_SCRIPT_BYTES:
        raise BridgeError(f"pyRevit script exceeds {MAX_SCRIPT_BYTES} bytes.")
    return data, hashlib.sha256(data).hexdigest()


def _load_approved_plan(plan_id: str, workspace: Any) -> Dict[str, Any]:
    if not plan_id or not re.fullmatch(r"[A-Za-z0-9_\-]+", plan_id):
        raise BridgeError("A valid plan_id of an approved plan is required.")
    path = Path(workspace.allowed_directories[0]) / "plans" / f"{plan_id}.json"
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BridgeError(f"Plan '{plan_id}' does not exist.") from exc
    if plan.get("state") != "approved":
        raise BridgeError(f"Plan '{plan_id}' is in state '{plan.get('state')}', not 'approved'. Execution blocked.")
    return plan


class PyrevitBridgeModule:

    def list_pyrevit_scripts(self, **_) -> Dict[str, Any]:
        dirs = _extension_dirs()
        scripts: List[Dict[str, Any]] = []
        for idx, root in enumerate(dirs):
            monitor = WorkspaceMonitor([root])
            for ext in sorted(p for p in root.rglob("*.extension") if p.is_dir()):
                for script in sorted(ext.rglob("*.pushbutton/script.py")):
                    try:
                        resolved = monitor.assert_in_workspace(script)
                        data, _sha = _read_script(resolved)
                    except (WorkspaceViolation, BridgeError, OSError):
                        continue
                    text = data.decode("utf-8", errors="replace")
                    rel = script.relative_to(root).as_posix()
                    parts = script.relative_to(ext).parts
                    tab = next((p[:-4] for p in parts if p.endswith(".tab")), None)
                    panel = next((p[:-6] for p in parts if p.endswith(".panel")), None)
                    writes = detect_write_calls(text)
                    scripts.append({
                        "id": f"{idx}:{rel}",
                        "title": script.parent.name[: -len(".pushbutton")],
                        "extension": ext.name,
                        "tab": tab,
                        "panel": panel,
                        "description": _docstring(text),
                        "has_write_calls": bool(writes),
                    })
        return {
            "extension_dirs_configured": len(dirs),
            "env_var": ENV_VAR,
            "count": len(scripts),
            "scripts": scripts,
        }

    def plan_run_pyrevit_script(self, script_id: str, **_) -> Dict[str, Any]:
        """Build an ActionPlan draft. Reads and hashes the file; never executes it."""
        path = _resolve_script(script_id, _extension_dirs())
        data, sha = _read_script(path)
        writes = detect_write_calls(data.decode("utf-8", errors="replace"))
        return {
            "plan_type": "action_plan_draft",
            "tool": "plan_run_pyrevit_script",
            "arguments": {"script_id": script_id},
            "preview": {
                "script_id": script_id,
                "script_path": str(path),
                "script_sha256": sha,
                "write_call_lines": writes,
                "write_calls_detected": bool(writes),
                "description": (
                    f"Run pyRevit script '{script_id}' (sha256 {sha[:12]}...). "
                    f"{len(writes)} line(s) look like model-write calls; detection is a heuristic, "
                    "treat the script as able to modify the model."
                ),
                "executes_on_plan": False,
            },
            "requires_approval": True,
            "actions": [{
                "tool": RUN_TOOL,
                "arguments": {"script_id": script_id, "script_sha256": sha},
            }],
        }

    def run_pyrevit_script(
        self,
        script_id: str,
        script_sha256: str,
        plan_id: str,
        workspace: Any = None,
        tool_executor: Any = None,
        **_,
    ) -> Dict[str, Any]:
        plan = _load_approved_plan(plan_id, workspace)
        approved = any(
            a.get("tool") == RUN_TOOL
            and a.get("arguments", {}).get("script_id") == script_id
            and a.get("arguments", {}).get("script_sha256") == script_sha256
            for a in plan.get("actions", [])
        )
        if not approved:
            raise BridgeError("Approved plan does not contain this script_id and script_sha256.")

        path = _resolve_script(script_id, _extension_dirs())
        data, sha = _read_script(path)
        if sha != script_sha256:
            raise BridgeError(
                "Script changed since the plan was approved (SHA-256 mismatch); "
                "create and approve a new plan."
            )

        if tool_executor is None:
            return self._unavailable(script_id, sha, "no tool executor available")
        try:
            result = tool_executor(BRIDGE_TOOL, {
                "script_id": script_id,
                "script_sha256": sha,
                "script_source": data.decode("utf-8", errors="replace"),
                "plan_id": plan_id,
            })
        except BridgeError as exc:
            return self._unavailable(script_id, sha, str(exc))
        return {"status": "executed", "script_id": script_id, "script_sha256": sha, "result": result}

    @staticmethod
    def _unavailable(script_id: str, sha: str, reason: str) -> Dict[str, Any]:
        return {
            "status": "bridge_unavailable",
            "executed": False,
            "script_id": script_id,
            "script_sha256": sha,
            "required_bridge_call": BRIDGE_CALL,
            "reason": reason,
            "note": "All approval and hash checks passed, but the Revit-side runner is not implemented.",
        }
