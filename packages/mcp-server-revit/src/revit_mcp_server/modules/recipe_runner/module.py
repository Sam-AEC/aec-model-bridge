"""
Recipe Runner — P15 AI Agent Orchestration.

Recipe format (YAML):
  id: recipe_id
  name: Human name
  description: ...
  steps:
    - id: step_id
      tool: tool_name          # e.g. "model_inspector_summarize_model"
      args:                    # static args
        snapshot_id: "{{snapshot_id}}"
      capture_as: snap_summary  # optional: store result under this key
    - id: step_2
      tool: qaqc_checker_run_check
      args:
        snapshot_id: "{{snapshot_id}}"
      condition: "{{prev.total_findings}} >= 0"  # always run
      capture_as: qaqc_result

Template variables: {{key}} → replaced from context dict.
Condition: minimal eval — supports == != >= <= comparisons on {{prev.field}}.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

RECIPES_DIR = Path(__file__).parent / "recipes"
RUN_LOG_FILE = "recipe_runs.json"
ToolExecutor = Callable[[str, Dict[str, Any]], Dict[str, Any]]


# ---------------------------------------------------------------------------
# Template engine (minimal — no exec, no eval on untrusted input)
# ---------------------------------------------------------------------------

def _render(value: Any, context: Dict[str, Any]) -> Any:
    """Recursively substitute {{key}} and {{obj.field}} placeholders."""
    if isinstance(value, str):
        def _sub(m: re.Match) -> str:
            expr = m.group(1).strip()
            parts = expr.split(".")
            node: Any = context
            for p in parts:
                if isinstance(node, dict):
                    node = node.get(p)
                else:
                    node = getattr(node, p, None)
                if node is None:
                    return ""
            return str(node) if node is not None else ""
        return re.sub(r"\{\{([^}]+)\}\}", _sub, value)
    if isinstance(value, dict):
        return {k: _render(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [_render(v, context) for v in value]
    return value

def _check_condition(condition: Optional[str], context: Dict[str, Any]) -> bool:
    if not condition:
        return True
    rendered = _render(condition, context)
    # Simple comparison: X >= Y, X == Y, etc.
    m = re.match(r"^(.+?)\s*(==|!=|>=|<=|>|<)\s*(.+)$", rendered.strip())
    if not m:
        return bool(rendered)
    lhs, op, rhs = m.group(1).strip(), m.group(2), m.group(3).strip()
    try:
        lhs_v: Any = float(lhs) if "." in lhs else int(lhs)
        rhs_v: Any = float(rhs) if "." in rhs else int(rhs)
    except (ValueError, TypeError):
        lhs_v, rhs_v = lhs, rhs
    ops = {"==": lhs_v == rhs_v, "!=": lhs_v != rhs_v, ">=": lhs_v >= rhs_v, "<=": lhs_v <= rhs_v, ">": lhs_v > rhs_v, "<": lhs_v < rhs_v}
    return ops.get(op, False)


# ---------------------------------------------------------------------------
# Recipe loader
# ---------------------------------------------------------------------------

def _workspace_path(path: Path, workspace: Any) -> Path:
    if not workspace or not getattr(workspace, "allowed_directories", None):
        raise ValueError("Workspace is required to load recipe files.")
    roots = [Path(root).resolve() for root in workspace.allowed_directories]
    resolved = path.resolve()
    if not any(resolved.is_relative_to(root) for root in roots):
        raise ValueError(f"Recipe file '{resolved}' is outside the allowed workspace.")
    return resolved

def _load_recipe(recipe_id: str, workspace: Any = None) -> Dict[str, Any]:
    candidate = Path(recipe_id)
    looks_like_path = candidate.is_absolute() or candidate.suffix in {".yaml", ".yml"} or len(candidate.parts) > 1
    if looks_like_path:
        if candidate.is_absolute():
            path = _workspace_path(candidate, workspace)
        else:
            if not workspace or not getattr(workspace, "allowed_directories", None):
                raise ValueError("Workspace is required to load recipe files.")
            path = _workspace_path(Path(workspace.allowed_directories[0]) / candidate, workspace)
    else:
        path = RECIPES_DIR / f"{recipe_id}.yaml"
    if not path.exists():
        raise ValueError(f"Recipe '{recipe_id}' not found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data.get("steps", []), list):
        raise ValueError(f"Recipe '{recipe_id}' has invalid steps.")
    return data

def _list_recipes() -> List[Dict[str, Any]]:
    if not RECIPES_DIR.exists():
        return []
    result = []
    for p in sorted(RECIPES_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
            result.append({"id": data.get("id", p.stem), "name": data.get("name", ""), "description": data.get("description", "")})
        except Exception:
            pass
    return result


# ---------------------------------------------------------------------------
# Run log
# ---------------------------------------------------------------------------

def _run_log_path(workspace: Any) -> Path:
    if not workspace:
        raise ValueError("Workspace is required for recipe run logs.")
    return workspace.allowed_directories[0] / RUN_LOG_FILE

def _load_runs(workspace: Any) -> List[Dict[str, Any]]:
    if not workspace:
        return []
    p = _run_log_path(workspace)
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return []

def _save_run(run: Dict[str, Any], workspace: Any) -> None:
    runs = _load_runs(workspace)
    runs.append(run)
    with open(_run_log_path(workspace), "w", encoding="utf-8") as f:
        json.dump(runs, f, indent=2, default=str)

def _run_status(step_results: List[Dict[str, Any]], dry_run: bool) -> str:
    if any("error" in step for step in step_results):
        return "failed"
    if dry_run:
        return "dry_run"
    if any(step.get("pending") for step in step_results):
        return "pending"
    return "completed"


# ---------------------------------------------------------------------------
# Module class
# ---------------------------------------------------------------------------

class RecipeRunnerModule:

    def run_recipe(
        self,
        recipe_id: str,
        args: Dict[str, Any] = None,
        dry_run: bool = False,
        workspace: Any = None,
        tool_executor: Any = None,  # Callable[str, dict] → dict (injected by provider)
        **_,
    ) -> Dict[str, Any]:
        recipe = _load_recipe(recipe_id, workspace)
        steps = recipe.get("steps", [])
        context: Dict[str, Any] = dict(args or {})

        run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()

        step_results = []
        prev: Dict[str, Any] = {}

        for step in steps:
            step_id = step.get("id", "?")
            tool_name = step.get("tool", "")
            raw_args = step.get("args", {})
            condition = step.get("condition")
            capture_as = step.get("capture_as")

            # Inject prev
            context["prev"] = prev

            if not _check_condition(condition, context):
                step_results.append({"step": step_id, "skipped": True, "reason": "condition_false"})
                continue

            rendered_args = _render(raw_args, context)

            if dry_run:
                step_results.append({"step": step_id, "tool": tool_name, "args": rendered_args, "dry_run": True})
                continue

            if tool_executor:
                try:
                    result = tool_executor(tool_name, rendered_args)
                    if result is None:
                        result = {}
                    prev = result
                    if capture_as:
                        context[capture_as] = result
                    step_results.append({"step": step_id, "tool": tool_name, "result": result})
                except Exception as e:
                    step_results.append({"step": step_id, "tool": tool_name, "error": str(e)})
                    break
            else:
                # No executor — record pending
                step_results.append({"step": step_id, "tool": tool_name, "args": rendered_args, "pending": True})

        status = _run_status(step_results, dry_run)
        finished_at = datetime.now(timezone.utc).isoformat()
        run = {
            "run_id": run_id,
            "recipe_id": recipe_id,
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "dry_run": dry_run,
            "steps": step_results,
        }

        if workspace:
            _save_run(run, workspace)

        return {
            "run_id": run_id,
            "recipe_id": recipe_id,
            "status": status,
            "steps_total": len(steps),
            "steps_run": len(step_results),
            "dry_run": dry_run,
            "finished_at": finished_at,
            "steps": step_results,
        }

    def list_recipes(self, **_) -> Dict[str, Any]:
        recipes = _list_recipes()
        return {"count": len(recipes), "recipes": recipes}

    def list_runs(self, recipe_id: str = "", workspace: Any = None, **_) -> Dict[str, Any]:
        runs = _load_runs(workspace)
        if recipe_id:
            runs = [r for r in runs if r.get("recipe_id") == recipe_id]
        return {"count": len(runs), "runs": runs}

    def get_run_status(self, run_id: str, workspace: Any = None, **_) -> Dict[str, Any]:
        for run in _load_runs(workspace):
            if run.get("run_id") == run_id:
                return run
        raise ValueError(f"Recipe run '{run_id}' not found.")
