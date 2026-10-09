"""
sheet_view_audit module - read-only sheet and view checks over a saved snapshot.

Command:
  run_audit - empty sheets, views not on any sheet, duplicate sheet numbers,
              sheets missing required parameters, default view names, and
              sheet counts per discipline prefix.

Snapshot data contract (UNVERIFIED against live Revit; the add-in does not
write this yet). The snapshot JSON may carry two optional top-level lists:

  "sheets": [{"uid", "number", "name", "view_uids": [...], "params": {name: value}}]
  "views":  [{"uid", "name", "view_type", "is_template", "sheet_uid", "discipline"}]

When neither list is present the audit says so instead of guessing.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

DEFAULT_REQUIRED = ["Sheet Number", "Sheet Name"]

# View types that Revit never places on a sheet.
_UNPLACEABLE_TYPES = {"projectbrowser", "systembrowser", "internal", "undefined", "revisionschedule"}

_DEFAULT_NAME_PATTERNS = [
    (re.compile(r"^\s*copy of\b", re.I), "starts with 'Copy of'"),
    (re.compile(r"\bcopy\s*\d*\s*$", re.I), "ends with 'Copy'"),
    (re.compile(r"^\s*\{3D[^}]*\}\s*$", re.I), "is the default '{3D}' name"),
    (re.compile(r"^\s*(section|detail|callout|elevation|drafting view)\s+\d+\s*$", re.I), "is a Revit default name"),
]

_SEV_ORDER = {"error": 0, "warning": 1, "info": 2}


def _finding(check: str, severity: str, message: str, uids: List[Any], next_step: str) -> Dict[str, Any]:
    return {
        "check": check,
        "severity": severity,
        "message": message,
        "unique_ids": sorted({u for u in uids if u}),
        "next_step": next_step,
    }


def _sheet_value(sheet: Dict[str, Any], param: str) -> Any:
    key = param.strip().lower()
    if key in ("sheet number", "number"):
        return sheet.get("number")
    if key in ("sheet name", "name"):
        return sheet.get("name")
    for k, v in (sheet.get("params") or {}).items():
        if k.strip().lower() == key:
            return v.get("v") if isinstance(v, dict) else v
    return None


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _prefix(number: Any) -> str:
    m = re.match(r"^\s*([A-Za-z]+)", str(number or ""))
    return m.group(1).upper() if m else "(none)"


def _default_name_reason(name: str) -> str:
    for pattern, reason in _DEFAULT_NAME_PATTERNS:
        if pattern.search(name or ""):
            return reason
    return ""


def _preview(names: List[str], limit: int = 5) -> str:
    text = ", ".join(names[:limit])
    return text + ("..." if len(names) > limit else "")


def audit_sheets_and_views(
    sheets: List[Dict[str, Any]],
    views: List[Dict[str, Any]],
    required_params: List[str],
) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []

    placed = set()
    for s in sheets:
        placed.update(s.get("view_uids") or [])
    for v in views:
        if v.get("sheet_uid"):
            placed.add(v.get("uid"))

    # 1. Empty sheets
    empty = [
        s for s in sheets
        if not (s.get("view_uids") or [])
        and not any(v.get("sheet_uid") == s.get("uid") for v in views)
    ]
    if empty:
        findings.append(_finding(
            "empty_sheets", "warning",
            f"{len(empty)} sheet(s) have no views on them: "
            + _preview([f"{s.get('number', '?')} {s.get('name', '')}".strip() for s in empty]),
            [s.get("uid") for s in empty],
            "Place a view on each of these sheets, or delete the sheets if they are not needed.",
        ))

    # 2. Views not on any sheet
    unplaced = [
        v for v in views
        if not v.get("is_template")
        and str(v.get("view_type", "")).replace(" ", "").lower() not in _UNPLACEABLE_TYPES
        and v.get("uid") not in placed
    ]
    if unplaced:
        findings.append(_finding(
            "views_not_on_sheet", "info",
            f"{len(unplaced)} view(s) are not placed on any sheet: "
            + _preview([str(v.get("name", "?")) for v in unplaced]),
            [v.get("uid") for v in unplaced],
            "Put each view on a sheet if it should be issued, or delete it if it is a leftover working view.",
        ))

    # 3. Duplicate sheet numbers
    by_number: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for s in sheets:
        num = str(s.get("number") or "").strip()
        if num:
            by_number[num.lower()].append(s)
    dupes = [group for group in by_number.values() if len(group) > 1]
    if dupes:
        findings.append(_finding(
            "duplicate_sheet_numbers", "error",
            f"{len(dupes)} sheet number(s) are used more than once: "
            + _preview([str(group[0].get("number")) for group in dupes]),
            [s.get("uid") for group in dupes for s in group],
            "Renumber the duplicate sheets so every sheet number is unique.",
        ))

    # 4. Missing required parameters
    for param in required_params:
        missing = [s for s in sheets if _is_blank(_sheet_value(s, param))]
        if missing:
            findings.append(_finding(
                "missing_sheet_parameter", "warning",
                f"{len(missing)} sheet(s) have an empty '{param}'.",
                [s.get("uid") for s in missing],
                f"Fill in '{param}' on these sheets.",
            ))

    # 5. Default view names
    bad = [v for v in views if not v.get("is_template") and _default_name_reason(str(v.get("name", "")))]
    if bad:
        findings.append(_finding(
            "default_view_names", "info",
            f"{len(bad)} view(s) still have a default or copied name: "
            + _preview([f"'{v.get('name')}'" for v in bad]),
            [v.get("uid") for v in bad],
            "Rename these views to match your office view naming standard.",
        ))

    findings.sort(key=lambda f: _SEV_ORDER[f["severity"]])

    counts: Dict[str, int] = defaultdict(int)
    for s in sheets:
        counts[_prefix(s.get("number"))] += 1
    view_discipline: Dict[str, int] = defaultdict(int)
    for v in views:
        if v.get("discipline"):
            view_discipline[str(v["discipline"])] += 1

    return {
        "status": "ok",
        "sheet_count": len(sheets),
        "view_count": len(views),
        "sheets_per_discipline_prefix": dict(sorted(counts.items())),
        "views_per_discipline": dict(sorted(view_discipline.items())),
        "total_findings": len(findings),
        "by_severity": {sev: sum(1 for f in findings if f["severity"] == sev) for sev in _SEV_ORDER},
        "findings": findings,
    }


class SheetViewAuditModule:

    def run_audit(
        self,
        snapshot_id: str = "",
        required_sheet_parameters: Optional[List[str]] = None,
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        if not snapshot_id:
            raise ValueError("sheet_view_audit_run_audit needs a snapshot_id. Take a snapshot first and pass its id.")
        path = workspace.allowed_directories[0] / "snapshots" / f"{snapshot_id}.json"
        if not path.exists():
            raise ValueError(f"Snapshot '{snapshot_id}' not found.")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        if "sheets" not in data and "views" not in data:
            return {
                "status": "no_sheet_view_data",
                "message": (
                    "This snapshot does not contain sheet or view data, so nothing was checked. "
                    "The Revit add-in does not export sheets and views into snapshots yet."
                ),
                "total_findings": 0,
                "findings": [],
            }

        required = DEFAULT_REQUIRED if required_sheet_parameters is None else list(required_sheet_parameters)
        result = audit_sheets_and_views(data.get("sheets") or [], data.get("views") or [], required)
        result["snapshot_id"] = snapshot_id
        result["required_sheet_parameters"] = required
        return result
