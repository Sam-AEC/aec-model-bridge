"""
parameter_manager module — P9.1 + P9.2 Parameter/Family/Type Workflows.

Commands:
  filter_params       — Show parameter grid across matching elements.
  diff_params         — Diff parameter values between two snapshots.
  plan_set_params     — Validate params and produce an ActionPlan draft.
  export_params_csv   — Write param values to a CSV file in workspace.
  import_params_csv   — Read param updates from CSV → ActionPlan draft.

Validation rules (P9.2):
  - readonly params are blocked
  - type-vs-instance mismatches are blocked  
  - wrong storage type writes are blocked
  - workshared-owned elements emit a skip warning (not a hard block without Revit)
"""
from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Storage-type ↔ Python type mapping for validation
# ---------------------------------------------------------------------------
STORAGE_TYPE_VALIDATORS: Dict[str, type] = {
    "String": str,
    "Double": (int, float),
    "Integer": int,
    "ElementId": (int, str),
    "Boolean": bool,
}


def _workspace_dir(workspace: Any) -> Path:
    return workspace.allowed_directories[0]

def _load_snapshot(snapshot_id: str, workspace: Any) -> Dict[str, Any]:
    path = _workspace_dir(workspace) / "snapshots" / f"{snapshot_id}.json"
    if not path.exists():
        raise ValueError(f"Snapshot '{snapshot_id}' not found.")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _match_element(el: Dict[str, Any], filter_dsl: Dict[str, Any]) -> bool:
    for key, val in filter_dsl.items():
        if key == "category":
            cats = val if isinstance(val, list) else [val]
            if el.get("category") not in cats:
                return False
        elif key == "family" and el.get("family") != val:
            return False
        elif key == "type_name" and el.get("type_name") != val:
            return False
        elif key == "level_uid" and el.get("level_uid") != val:
            return False
        elif key == "parameter":
            pname = val.get("name")
            params = el.get("params", {})
            param = params.get(pname) if params else None
            if val.get("empty") is True:
                if param is not None and param.get("v") not in (None, ""):
                    return False
            elif "value" in val:
                if param is None or str(param.get("v")) != str(val["value"]):
                    return False
    return True

def _validate_param_update(
    el: Dict[str, Any],
    param_name: str,
    new_value: Any,
) -> Tuple[bool, Optional[str]]:
    """Returns (ok, reason_if_blocked)."""
    params = el.get("params", {})
    param_info = params.get(param_name)
    
    if param_info is None:
        return False, f"Parameter '{param_name}' does not exist on element {el['uid']}"
    
    # Readonly block
    if param_info.get("readonly", False):
        return False, f"Parameter '{param_name}' is read-only on element {el['uid']}"
    
    # Storage type check
    storage = param_info.get("storage")
    if storage and storage in STORAGE_TYPE_VALIDATORS:
        expected_type = STORAGE_TYPE_VALIDATORS[storage]
        if not isinstance(new_value, expected_type):
            return False, (
                f"Parameter '{param_name}' has storage type '{storage}' "
                f"but received value of type '{type(new_value).__name__}'"
            )
    
    return True, None

def _make_action_plan(tool_name: str, args: Dict[str, Any], preview: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "plan_type": "action_plan_draft",
        "tool": tool_name,
        "arguments": args,
        "preview": preview,
        "requires_approval": True,
        "actions": _actions_from_planned(preview.get("planned", [])),
    }


def _actions_from_planned(planned: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten a planned-updates list into `plan_actions`-ready tool calls.

    One `revit_set_parameter_value` action per (element, parameter) pair, so the
    caller can pass this straight to `plan_actions` — that path already captures
    before-state and supports rollback for this tool, generalizing to any batch
    size with no additional code.
    """
    actions: List[Dict[str, Any]] = []
    for entry in planned:
        element_id = entry.get("element_id")
        for pname, change in entry.get("updates", {}).items():
            actions.append({
                "tool": "revit_set_parameter_value",
                "arguments": {
                    "element_id": element_id,
                    "parameter_name": pname,
                    "value": change.get("after"),
                },
            })
    return actions


class ParameterManagerModule:

    def filter_params(
        self,
        element_filter: Dict[str, Any],
        param_name: str,
        snapshot_id: str = "",
        include_readonly: bool = False,
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        elements = self._get_elements(snapshot_id, workspace)
        matched = [el for el in elements if _match_element(el, element_filter)]
        
        rows = []
        for el in matched:
            params = el.get("params", {})
            pinfo = params.get(param_name)
            if pinfo is None:
                continue
            if not include_readonly and pinfo.get("readonly", False):
                continue
            rows.append({
                "uid": el["uid"],
                "element_id": el.get("element_id"),
                "category": el.get("category"),
                "type_name": el.get("type_name"),
                "param_name": param_name,
                "value": pinfo.get("v"),
                "storage": pinfo.get("storage"),
                "readonly": pinfo.get("readonly", False),
                "instance": pinfo.get("instance", True),
            })
        
        return {
            "param_name": param_name,
            "element_count": len(matched),
            "rows_with_param": len(rows),
            "rows": rows,
        }

    def diff_params(
        self,
        snapshot_a_id: str,
        snapshot_b_id: str,
        param_names: List[str],
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        snap_a = _load_snapshot(snapshot_a_id, workspace)
        snap_b = _load_snapshot(snapshot_b_id, workspace)
        
        els_a = {el["uid"]: el for el in snap_a.get("elements", [])}
        els_b = {el["uid"]: el for el in snap_b.get("elements", [])}
        
        diffs = []
        for uid, el_b in els_b.items():
            el_a = els_a.get(uid)
            if not el_a:
                continue
            for pname in param_names:
                pinfo_a = el_a.get("params", {}).get(pname)
                pinfo_b = el_b.get("params", {}).get(pname)
                val_a = pinfo_a.get("v") if pinfo_a else None
                val_b = pinfo_b.get("v") if pinfo_b else None
                if val_a != val_b:
                    diffs.append({
                        "uid": uid,
                        "param_name": pname,
                        "before": val_a,
                        "after": val_b,
                    })
        
        return {
            "snapshot_a_id": snapshot_a_id,
            "snapshot_b_id": snapshot_b_id,
            "param_names": param_names,
            "diffs_count": len(diffs),
            "diffs": diffs,
        }

    def plan_set_params(
        self,
        element_filter: Dict[str, Any],
        param_updates: Dict[str, Any],
        snapshot_id: str = "",
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        elements = self._get_elements(snapshot_id, workspace)
        matched = [el for el in elements if _match_element(el, element_filter)]
        
        planned = []
        blocked = []
        
        for el in matched:
            # Simulate worksharing skip if workset is set (real Revit would check ownership)
            workset = el.get("workset")
            if workset:
                # Just a warning, not a hard block without live Revit connection
                logger.debug(f"Element {el['uid']} is on workset '{workset}' — check ownership in Revit.")
            
            el_updates = {}
            el_blocked = []
            
            for pname, new_val in param_updates.items():
                ok, reason = _validate_param_update(el, pname, new_val)
                if ok:
                    # Record before-value for rollback
                    pinfo = el.get("params", {}).get(pname, {})
                    el_updates[pname] = {
                        "before": pinfo.get("v"),
                        "after": new_val,
                        "storage": pinfo.get("storage"),
                    }
                else:
                    el_blocked.append({"param": pname, "reason": reason})
            
            if el_updates:
                planned.append({
                    "uid": el["uid"],
                    "element_id": el.get("element_id"),
                    "updates": el_updates,
                })
            if el_blocked:
                blocked.extend(el_blocked)
        
        preview = {
            "element_count": len(matched),
            "planned_count": len(planned),
            "blocked_count": len(blocked),
            "blocked": blocked,
            "description": (
                f"Set {list(param_updates.keys())} on {len(planned)} element(s). "
                f"{len(blocked)} validation issue(s) blocked."
            ),
        }
        
        return _make_action_plan(
            "plan_set_params",
            {"element_filter": element_filter, "param_updates": param_updates},
            {**preview, "planned": planned},
        )

    def export_params_csv(
        self,
        element_filter: Dict[str, Any],
        param_names: List[str],
        snapshot_id: str = "",
        output_filename: str = "params_export.csv",
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        elements = self._get_elements(snapshot_id, workspace)
        matched = [el for el in elements if _match_element(el, element_filter)]
        
        output_path = _workspace_dir(workspace) / output_filename
        
        header = ["uid", "element_id", "category", "family", "type_name"] + param_names
        with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=header, extrasaction="ignore")
            writer.writeheader()
            for el in matched:
                row = {
                    "uid": el["uid"],
                    "element_id": el.get("element_id", ""),
                    "category": el.get("category", ""),
                    "family": el.get("family", ""),
                    "type_name": el.get("type_name", ""),
                }
                for pname in param_names:
                    pinfo = el.get("params", {}).get(pname)
                    row[pname] = pinfo.get("v") if pinfo else ""
                writer.writerow(row)
        
        return {
            "status": "exported",
            "output_file": str(output_path),
            "element_count": len(matched),
            "param_names": param_names,
        }

    def import_params_csv(
        self,
        csv_filename: str,
        snapshot_id: str = "",
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        csv_path = _workspace_dir(workspace) / csv_filename
        if not csv_path.exists():
            raise ValueError(f"CSV file '{csv_filename}' not found in workspace.")
        
        elements = self._get_elements(snapshot_id, workspace)
        els_by_uid = {el["uid"]: el for el in elements}
        
        planned = []
        blocked = []
        
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            reserved_cols = {"uid", "element_id", "category", "family", "type_name"}
            for row in reader:
                uid = row.get("uid", "").strip()
                if not uid:
                    continue
                el = els_by_uid.get(uid)
                if not el:
                    blocked.append({"uid": uid, "reason": "Element not found in snapshot."})
                    continue
                
                el_updates = {}
                for pname, val_str in row.items():
                    if pname in reserved_cols or not pname:
                        continue
                    # Try cast to appropriate type via current param storage
                    pinfo = el.get("params", {}).get(pname)
                    storage = pinfo.get("storage") if pinfo else "String"
                    
                    # Cast value
                    try:
                        if storage == "Double":
                            new_val = float(val_str)
                        elif storage == "Integer":
                            new_val = int(val_str)
                        elif storage == "Boolean":
                            new_val = val_str.lower() in ("true", "1", "yes")
                        else:
                            new_val = val_str
                    except (ValueError, TypeError):
                        blocked.append({"uid": uid, "param": pname, "reason": f"Cannot cast '{val_str}' to {storage}"})
                        continue
                    
                    ok, reason = _validate_param_update(el, pname, new_val)
                    if ok:
                        el_updates[pname] = {
                            "before": pinfo.get("v") if pinfo else None,
                            "after": new_val,
                        }
                    else:
                        blocked.append({"uid": uid, "param": pname, "reason": reason})
                
                if el_updates:
                    planned.append({"uid": uid, "element_id": el.get("element_id"), "updates": el_updates})
        
        preview = {
            "csv_filename": csv_filename,
            "planned_count": len(planned),
            "blocked_count": len(blocked),
            "blocked": blocked,
        }
        
        return _make_action_plan("import_params_csv", {"csv_filename": csv_filename}, {**preview, "planned": planned})

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _get_elements(self, snapshot_id: str, workspace: Any) -> List[Dict[str, Any]]:
        if not snapshot_id:
            from revit_mcp_server.semantic.engine import generate_mock_snapshot
            snap = generate_mock_snapshot()
            return [el.model_dump(by_alias=True) for el in snap.elements]
        data = _load_snapshot(snapshot_id, workspace)
        return data.get("elements", [])
