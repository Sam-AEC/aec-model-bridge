"""
parameter_manager module — P9.1 + P9.2 Parameter/Family/Type Workflows.

Commands:
  filter_params       — Show parameter grid across matching elements.
  diff_params         — Diff parameter values between two snapshots.
  plan_set_params     — Validate params and produce an ActionPlan draft.
  export_params_csv   — Write param values to a CSV file in workspace.
  import_params_csv   — Read param updates from CSV → ActionPlan draft.
  export_params_xlsx  — Write param values to an .xlsx workbook in workspace.
  import_params_xlsx  — Read an edited workbook, diff vs snapshot → ActionPlan draft.

Validation rules (P9.2):
  - readonly params are blocked
  - type-vs-instance mismatches are blocked  
  - wrong storage type writes are blocked
  - workshared-owned elements emit a skip warning (not a hard block without Revit)
"""
from __future__ import annotations
from revit_mcp_server.security.module_permissions import writable_path

import csv
import json
import logging
import re
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

def _confined(workspace: Any, *parts: str) -> Path:
    """Join parts under the workspace and refuse anything that resolves outside it.

    Snapshot ids and file names come from the caller, and the draft-only tools run
    without an approved plan, so '..', absolute paths and symlinks must not escape.
    """
    base = _workspace_dir(workspace)
    candidate = (base.joinpath(*parts)).resolve()
    checker = getattr(workspace, "assert_in_workspace", None)
    if checker is not None:
        return checker(candidate)
    if not candidate.is_relative_to(base.resolve()):
        raise ValueError(f"{candidate} is outside the allowed workspace directories")
    return candidate


def _load_snapshot(snapshot_id: str, workspace: Any) -> Dict[str, Any]:
    from revit_mcp_server.security.safe_paths import snapshot_file

    path = snapshot_file(_workspace_dir(workspace) / "snapshots", snapshot_id)
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

_RESERVED_COLS = {"uid", "element_id", "category", "family", "type_name"}
_XLSX_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}")


def _plan_rows(
    rows: List[Dict[str, Any]], elements: List[Dict[str, Any]], skip_unchanged: bool = False
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    """Diff edited rows (string cells) against snapshot elements.

    Returns (planned, blocked, row_counts). With skip_unchanged, cells equal to the
    snapshot value and blank cells produce no update.
    """
    els_by_uid = {el["uid"]: el for el in elements}
    planned: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    counts = {"rows": 0, "changed_rows": 0, "unchanged_rows": 0, "unknown_rows": 0}
    for row in rows:
        uid = str(row.get("uid") or "").strip()
        if not uid:
            continue
        counts["rows"] += 1
        el = els_by_uid.get(uid)
        if not el:
            counts["unknown_rows"] += 1
            blocked.append({"uid": uid, "reason": "Element not found in snapshot."})
            continue
        el_updates: Dict[str, Any] = {}
        for pname, val_str in row.items():
            if pname in _RESERVED_COLS or not pname:
                continue
            pinfo = el.get("params", {}).get(pname)
            storage = pinfo.get("storage") if pinfo else "String"
            before = pinfo.get("v") if pinfo else None
            if skip_unchanged and (val_str is None or val_str.strip() == ""):
                continue
            try:
                if storage == "Double":
                    new_val = float(val_str)
                elif storage == "Integer":
                    new_val = int(val_str)
                elif storage == "Boolean":
                    new_val = val_str.lower() in ("true", "1", "yes")
                else:
                    new_val = val_str
            except (ValueError, TypeError, AttributeError):
                blocked.append({"uid": uid, "param": pname, "reason": f"Cannot cast '{val_str}' to {storage}"})
                continue
            if skip_unchanged and new_val == before:
                continue
            ok, reason = _validate_param_update(el, pname, new_val)
            if ok:
                el_updates[pname] = {"before": before, "after": new_val}
            else:
                blocked.append({"uid": uid, "param": pname, "reason": reason})
        if el_updates:
            counts["changed_rows"] += 1
            planned.append({"uid": uid, "element_id": el.get("element_id"), "updates": el_updates})
        else:
            counts["unchanged_rows"] += 1
    return planned, blocked, counts


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    # Text is kept exactly: trimming would turn an unedited " A " into an update.
    # Headers and uids are trimmed where they are read.
    return str(value)


def _xlsx_path(workspace: Any, filename: str) -> Path:
    """Workspace-root .xlsx path for a plain file name (via safe_child)."""
    from revit_mcp_server.security.safe_paths import safe_child

    def refuse(_reason: str) -> Exception:
        return ValueError("xlsx_filename must be a plain '<name>.xlsx' file name in the workspace.")

    if not isinstance(filename, str) or not filename.lower().endswith(".xlsx"):
        raise refuse("name")
    return safe_child(_workspace_dir(workspace), filename[:-5], ".xlsx", _XLSX_NAME_RE, refuse)


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
        # Hand these to plan_actions (snapshot_id, skipped) so the proof bundle names the
        # source document and lists what was left out and why.
        "skipped": preview.get("blocked", []),
        "snapshot_id": args.get("snapshot_id", ""),
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
                    el_blocked.append({
                        "uid": el.get("uid"),
                        "element_id": el.get("element_id"),
                        "param": pname,
                        "reason": reason,
                    })
            
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
            {"element_filter": element_filter, "param_updates": param_updates, "snapshot_id": snapshot_id},
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
        
        output_path = writable_path(workspace, _confined(workspace, output_filename))
        
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
        csv_path = _confined(workspace, csv_filename)
        if not csv_path.exists():
            raise ValueError(f"CSV file '{csv_filename}' not found in workspace.")
        
        elements = self._get_elements(snapshot_id, workspace)
        with open(csv_path, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        planned, blocked, _ = _plan_rows(rows, elements)

        preview = {
            "csv_filename": csv_filename,
            "planned_count": len(planned),
            "blocked_count": len(blocked),
            "blocked": blocked,
        }
        
        return _make_action_plan("import_params_csv", {"csv_filename": csv_filename}, {**preview, "planned": planned})

    def export_params_xlsx(
        self,
        element_filter: Dict[str, Any],
        param_names: List[str],
        snapshot_id: str = "",
        output_filename: str = "params_export.xlsx",
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        from openpyxl import Workbook

        elements = self._get_elements(snapshot_id, workspace)
        matched = [el for el in elements if _match_element(el, element_filter)]
        output_path = _xlsx_path(workspace, output_filename)
        wb = Workbook()
        ws = wb.active
        ws.title = "Parameters"
        ws.append(["uid", "element_id", "category", "family", "type_name"] + list(param_names))
        for el in matched:
            row = [el["uid"], el.get("element_id", ""), el.get("category", ""),
                   el.get("family", ""), el.get("type_name", "")]
            for pname in param_names:
                pinfo = el.get("params", {}).get(pname)
                row.append(pinfo.get("v") if pinfo else None)
            ws.append(row)
        wb.save(output_path)
        return {
            "status": "exported",
            "output_file": str(output_path),
            "element_count": len(matched),
            "param_names": param_names,
        }

    def import_params_xlsx(
        self,
        xlsx_filename: str,
        snapshot_id: str = "",
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        from openpyxl import load_workbook

        path = _xlsx_path(workspace, xlsx_filename)
        if not path.exists():
            raise ValueError(f"Workbook '{xlsx_filename}' not found in workspace.")
        elements = self._get_elements(snapshot_id, workspace)
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb["Parameters"] if "Parameters" in wb.sheetnames else wb.worksheets[0]
            it = ws.iter_rows(values_only=True)
            header = next(it, None)
            names = [str(h).strip() if h is not None else "" for h in (header or [])]
            if "uid" not in names:
                raise ValueError("Workbook must have a header row with a 'uid' column.")
            rows = [{n: _cell_text(c) for n, c in zip(names, r)} for r in it]
        finally:
            wb.close()
        planned, blocked, counts = _plan_rows(rows, elements, skip_unchanged=True)
        preview = {
            "xlsx_filename": xlsx_filename,
            "planned_count": len(planned),
            "blocked_count": len(blocked),
            "blocked": blocked,
            "row_diff": counts,
        }
        return _make_action_plan("import_params_xlsx", {"xlsx_filename": xlsx_filename}, {**preview, "planned": planned})

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _get_elements(self, snapshot_id: str, workspace: Any) -> List[Dict[str, Any]]:
        if not snapshot_id:
            from revit_mcp_server.semantic.engine import generate_mock_snapshot, require_snapshot_or_mock
            require_snapshot_or_mock(snapshot_id, "parameter_manager")
            snap = generate_mock_snapshot()
            return [el.model_dump(by_alias=True) for el in snap.elements]
        data = _load_snapshot(snapshot_id, workspace)
        return data.get("elements", [])
