"""
links_worksets_audit module - read-only audit of linked models and worksets.

Command:
  audit - Check links (unloaded, missing path, not pinned, Origin to Origin
          placement) and worksets (empty, default name, open by another user,
          elements on the wrong workset for their category).

Data sources (what the Revit add-in exposes today):
  revit_get_rvt_links       -> name, id, is_loaded, is_nested, path
  revit_get_link_instances  -> name, id, type_id, link_name
  revit_get_worksets        -> is_workshared, worksets[name, id, is_open]
  snapshot elements         -> category, workset (name)

GAPS (UNVERIFIED, not yet returned by the add-in; checks run only when the
field is present in the data, and the result lists each one under "gaps"):
  - link pinned state, link placement ("Auto - Origin to Origin" etc.),
    link kind (IFC / CAD), CAD links entirely
  - workset owner / default flag
  - per-workset element count (derived from a snapshot when one is given)
Nothing here has been run against live Revit.
"""
from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_WORKSET_RE = re.compile(r"^workset\s*\d*$", re.IGNORECASE)
ORIGIN_TO_ORIGIN = "origin to origin"
_UNKNOWN_PATHS = {"", "unknown", "none", "null"}
_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def _unwrap(data: Any, key: str) -> List[Dict[str, Any]]:
    """Accept a raw list or the add-in's {key: [...]} reply (possibly wrapped in 'result')."""
    if isinstance(data, dict) and key not in data and isinstance(data.get("result"), dict):
        data = data["result"]
    if isinstance(data, dict):
        data = data.get(key, [])
    return [d for d in (data or []) if isinstance(d, dict)]


def _finding(severity: str, area: str, rule: str, item: str, message: str, next_step: str, **extra: Any) -> Dict[str, Any]:
    out = {"severity": severity, "area": area, "rule": rule, "item": item, "message": message, "next_step": next_step}
    out.update(extra)
    return out


def _bool_or_none(v: Any) -> Optional[bool]:
    return v if isinstance(v, bool) else None


def check_links(
    links: List[Dict[str, Any]],
    instances: List[Dict[str, Any]],
    expect_shared_coordinates: bool = True,
    check_local_paths: bool = True,
) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    by_type: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for inst in instances:
        by_type[inst.get("type_id")].append(inst)

    for link in links:
        name = str(link.get("name", "(unnamed link)"))
        kind = link.get("kind") or link.get("link_kind") or "Revit"
        label = f"{kind} link '{name}'"

        if link.get("is_loaded") is False:
            findings.append(_finding(
                "warning", "link", "link_unloaded", name,
                f"{label} is unloaded, so its geometry is not in the model.",
                "In Manage Links, select the link and click Reload (or Reload From if the file moved).",
            ))

        path = link.get("path")
        if not link.get("is_nested") and (path is None or str(path).strip().lower() in _UNKNOWN_PATHS):
            findings.append(_finding(
                "error", "link", "link_missing_path", name,
                f"{label} has no file path, so Revit cannot find the source file.",
                "In Manage Links, use Reload From to point the link at the current file.",
            ))
        elif check_local_paths and path and re.match(r"^([A-Za-z]:[\\/]|\\\\)", str(path)) and not os.path.exists(str(path)):
            findings.append(_finding(
                "info", "link", "link_path_not_found_from_here", name,
                f"{label} points to '{path}', which this tool cannot see from where it runs.",
                "Open Manage Links in Revit and check the Status column. Ignore this if the tool runs on a different machine than Revit.",
            ))

        pinned_vals: List[bool] = []
        positions: List[str] = []
        for inst in by_type.get(link.get("id"), []) + [link]:
            p = _bool_or_none(inst.get("pinned"))
            if p is not None:
                pinned_vals.append(p)
            pos = inst.get("positioning") or inst.get("position_type")
            if pos:
                positions.append(str(pos))

        if pinned_vals and not all(pinned_vals):
            findings.append(_finding(
                "warning", "link", "link_not_pinned", name,
                f"{label} is not pinned and could be moved by accident.",
                "Select the link in a view and click Pin on the Modify tab.",
            ))
        if expect_shared_coordinates and any(ORIGIN_TO_ORIGIN in p.lower() for p in positions):
            findings.append(_finding(
                "warning", "link", "link_origin_to_origin", name,
                f"{label} is placed 'Auto - Origin to Origin' but this project is expected to use shared coordinates.",
                "Reload the link with Manage Links > Reload From, place it by Shared Coordinates (Acquire Coordinates if needed) and check it against the survey point.",
            ))
        if link.get("shared_coordinates_match") is False:
            findings.append(_finding(
                "error", "link", "link_coordinates_mismatch", name,
                f"{label} does not share coordinates with this model.",
                "Agree the shared coordinate origin with the link owner, then use Acquire or Publish Coordinates.",
            ))
    return findings


def check_worksets(
    data: Any,
    element_counts: Optional[Dict[str, int]] = None,
    current_user: str = "",
) -> List[Dict[str, Any]]:
    if isinstance(data, dict) and "worksets" not in data and isinstance(data.get("result"), dict):
        data = data["result"]
    if isinstance(data, dict) and data.get("is_workshared") is False:
        return [_finding(
            "info", "workset", "not_workshared", "(model)",
            "This model is not workshared, so there are no worksets to check.",
            "Nothing to do unless the model should be workshared (Collaborate > Collaborate).",
        )]
    findings: List[Dict[str, Any]] = []
    me = current_user.strip().lower()

    for ws in _unwrap(data, "worksets"):
        name = str(ws.get("name", "(unnamed)"))
        if ws.get("is_default") is True or DEFAULT_WORKSET_RE.match(name):
            findings.append(_finding(
                "warning", "workset", "workset_default_name", name,
                f"Workset '{name}' still has a default name, so nobody can tell what belongs on it.",
                "Rename it in Collaborate > Worksets (for example 'Architecture - Walls').",
            ))

        count = ws.get("element_count")
        if count is None and element_counts is not None:
            count = element_counts.get(name, 0)
        if count == 0:
            findings.append(_finding(
                "info", "workset", "workset_empty", name,
                f"Workset '{name}' has no elements.",
                "Delete it in Collaborate > Worksets if it is not needed, or keep it for planned content.",
            ))

        owner = str(ws.get("owner") or "").strip()
        if owner and owner.lower() != me:
            findings.append(_finding(
                "warning", "workset", "workset_open_by_other_user", name,
                f"Workset '{name}' is checked out by {owner}.",
                f"Ask {owner} to synchronize and relinquish it before you need to edit it.",
                owner=owner,
            ))
    return findings


def check_element_worksets(elements: List[Dict[str, Any]], category_map: Dict[str, str]) -> List[Dict[str, Any]]:
    wrong: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for el in elements:
        cat = el.get("category")
        expected = category_map.get(cat) if cat else None
        if expected is not None and (el.get("workset") or "") != expected:
            wrong[cat].append(el)
    findings = []
    for cat, els in sorted(wrong.items()):
        expected = category_map[cat]
        found_on = sorted({str(e.get("workset") or "(none)") for e in els})
        findings.append(_finding(
            "warning", "element_workset", "wrong_workset", cat,
            f"{len(els)} {cat} element(s) are not on workset '{expected}' (found on: {', '.join(found_on)}).",
            f"Select the {cat} elements and move them to '{expected}' using the workset drop-down in the status bar.",
            expected_workset=expected, count=len(els),
            sample_uids=[e.get("uid") for e in els[:10] if e.get("uid")],
        ))
    return findings


class LinksWorksetsAuditModule:

    def audit(
        self,
        snapshot_id: str = "",
        category_workset_map: Optional[Dict[str, str]] = None,
        current_user: str = "",
        expect_shared_coordinates: bool = True,
        links: Any = None,
        link_instances: Any = None,
        worksets: Any = None,
        workspace: Any = None,
        tool_executor: Any = None,
        **_,
    ) -> Dict[str, Any]:
        notes: List[str] = []
        live = False
        # Anything not supplied is read live from the Revit tools (read-only).
        if tool_executor is not None:
            for arg, tool in (("links", "revit_get_rvt_links"),
                              ("link_instances", "revit_get_link_instances"),
                              ("worksets", "revit_get_worksets")):
                if locals()[arg] is not None:
                    continue
                try:
                    value = tool_executor(tool, {})
                except Exception as exc:
                    notes.append(f"Could not read {tool} from Revit: {exc}")
                    continue
                live = True
                if arg == "links":
                    links = value
                elif arg == "link_instances":
                    link_instances = value
                else:
                    worksets = value

        elements = self._load_elements(snapshot_id, workspace) if snapshot_id else []

        findings: List[Dict[str, Any]] = []
        link_list = _unwrap(links, "links") if links is not None else []
        inst_list = _unwrap(link_instances, "instances") if link_instances is not None else []
        if links is not None:
            findings += check_links(link_list, inst_list, expect_shared_coordinates)
        else:
            notes.append("No link data available, so links were not checked.")

        counts: Optional[Dict[str, int]] = None
        if elements:
            counts = defaultdict(int)
            for el in elements:
                if el.get("workset"):
                    counts[str(el["workset"])] += 1
        ws_list = _unwrap(worksets, "worksets") if worksets is not None else []
        if worksets is not None:
            findings += check_worksets(worksets, counts, current_user)
        else:
            notes.append("No workset data available, so worksets were not checked.")

        if category_workset_map:
            if elements:
                findings += check_element_worksets(elements, category_workset_map)
            else:
                notes.append("A workset mapping was given but no snapshot_id, so element worksets were not checked.")

        findings.sort(key=lambda f: (_SEVERITY_ORDER.get(f["severity"], 9), f["area"], f["item"]))
        return {
            "total_findings": len(findings),
            "by_severity": {s: sum(1 for f in findings if f["severity"] == s) for s in ("error", "warning", "info")},
            "links_checked": len(link_list),
            "worksets_checked": len(ws_list),
            "findings": findings,
            "notes": notes,
            "gaps": self._gaps(link_list, inst_list, ws_list, counts is not None),
            "unverified": "UNVERIFIED: read-only and not yet run against live Revit; fields the add-in does not return are listed under gaps.",
            "source": "live_revit" if live else "supplied_data",
        }

    @staticmethod
    def _gaps(link_list, inst_list, ws_list, have_counts: bool) -> List[str]:
        gaps = []
        both = link_list + inst_list
        if link_list and not any("pinned" in d for d in both):
            gaps.append("UNVERIFIED: the add-in does not return pinned state for links, so 'not pinned' cannot be checked yet.")
        if link_list and not any(d.get("positioning") or d.get("position_type") for d in both):
            gaps.append("UNVERIFIED: the add-in does not return link placement (Origin to Origin vs shared coordinates), so that check cannot run yet.")
        if link_list and not any(d.get("kind") or d.get("link_kind") for d in link_list):
            gaps.append("UNVERIFIED: only Revit links are listed; IFC and CAD links are not exposed by the add-in yet.")
        if ws_list and not any("owner" in w for w in ws_list):
            gaps.append("UNVERIFIED: the add-in does not return who has a workset checked out, so 'open by another user' cannot be checked yet.")
        if ws_list and not have_counts and not any("element_count" in w for w in ws_list):
            gaps.append("The empty-workset check needs a snapshot_id (element counts per workset).")
        return gaps

    @staticmethod
    def _load_elements(snapshot_id: str, workspace: Any) -> List[Dict[str, Any]]:
        path = Path(workspace.allowed_directories[0]) / "snapshots" / f"{snapshot_id}.json"
        if not path.exists():
            raise ValueError(f"Snapshot '{snapshot_id}' not found.")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("elements", [])
