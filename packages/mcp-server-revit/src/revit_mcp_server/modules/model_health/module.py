"""
model_health module - a model health score per snapshot, and its trend over time.

Command:
  score - Health score (0 to 100, higher is better) of one saved snapshot with its components,
          and the same score for every saved snapshot of the same document (doc_guid), oldest
          first, with the change from the previous point. Optional CSV in the workspace.

Read-only. The formula is deterministic and uses only inputs that exist in the snapshot.
An input that is missing is left out and listed under ``excluded``; it is never scored as 0
or as 100. Score = sum(weight x subscore) / sum(weight) over the components that were used.

Components (subscore 0 to 100, weight):
  warnings      (25) counts.warnings, if the snapshot records it:
                     max(0, 100 - 5 x warnings per 1000 elements)
  qa_findings   (25) only when a rule_pack is given; rules run in memory:
                     100 x (1 - elements hit by an error or warning rule / elements)
  unplaced_rooms (20) when the snapshot has rooms:
                     100 x (1 - unplaced rooms / rooms); unplaced = no level and no location
  unused_types  (15) purgeable types: non-system types with no placed instance. Needs a type
                     list, instance records that match it, and a snapshot that is not partial:
                     100 x (1 - unused / non-system types)
  completeness  (15) fill rate of the 5 most common parameters per category (the heatmap tool):
                     100 x filled / total over those cells

A partial snapshot (truncated, dirty-only, category-filtered) is scored on what it holds and
flagged. A change between two points is only given when both are complete captures that used
the same components; otherwise ``delta`` is null with a reason.
"""
from __future__ import annotations
from revit_mcp_server.security.module_permissions import writable_path

import csv
import importlib.util
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

WEIGHTS = {"warnings": 25, "qa_findings": 25, "unplaced_rooms": 20, "unused_types": 15, "completeness": 15}
WARNINGS_PENALTY_PER_1000 = 5
COMPLETENESS_TOP_N = 5
DEFAULT_MAX_POINTS = 50
MAX_POINTS = 500


def _sibling(module_id: str) -> Any:
    path = Path(__file__).resolve().parent.parent / module_id / "module.py"
    spec = importlib.util.spec_from_file_location(f"_model_health_{module_id}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rg = _sibling("report_generator")
pc = _sibling("param_completeness")
_changes = _sibling("model_changes")


def _is_placed(el: Dict[str, Any]) -> bool:
    return el.get("level_uid") is not None or el.get("location") is not None


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


def compute_components(data: Dict[str, Any], rule_pack: str = "", workspace: Any = None) -> Dict[str, Any]:
    """Components for one loaded snapshot (see ``rg._load_review_snapshot``). Pure apart from rule loading."""
    elements = data.get("elements") or []
    types = data.get("types") or []
    counts = data.get("counts") or {}
    partial = rg._is_partial_snapshot(data)
    used: List[Dict[str, Any]] = []
    excluded: List[Dict[str, str]] = []

    def add(name: str, sub: float, inputs: Dict[str, Any]) -> None:
        used.append({"name": name, "weight": WEIGHTS[name], "subscore": round(_clamp(sub), 1), "inputs": inputs})

    def skip(name: str, reason: str) -> None:
        excluded.append({"name": name, "reason": reason})

    # warnings
    w = counts.get("warnings")
    if isinstance(w, (int, float)) and not isinstance(w, bool) and w >= 0 and elements:
        per_1000 = 1000.0 * w / len(elements)
        add("warnings", 100 - WARNINGS_PENALTY_PER_1000 * per_1000,
            {"warnings": int(w), "elements": len(elements), "warnings_per_1000_elements": round(per_1000, 2)})
    else:
        skip("warnings", "The snapshot does not record a warning count (counts.warnings)." if not elements or w is None
             else "counts.warnings is not a non-negative number.")

    # QA findings
    if rule_pack:
        failed: List[Any] = []
        groups = rg._review_findings(elements, types, (data.get("source") or {}).get("doc_guid") or data["snapshot_id"],
                                     rule_pack, workspace, failed)
        if failed:
            skip("qa_findings", "Rules could not run, so the result is unknown: " + ", ".join(map(str, failed)))
        elif not elements:
            skip("qa_findings", "The snapshot has no elements.")
        else:
            hit = {u for g in groups if g["severity"] in ("error", "warning") for u in g["uids"]}
            add("qa_findings", 100 * (1 - len(hit) / len(elements)),
                {"rule_pack": rule_pack, "elements_flagged": len(hit), "elements": len(elements)})
    else:
        skip("qa_findings", "No rule_pack was given, so QA rules were not run.")

    # unplaced rooms
    rooms = [e for e in elements if e.get("category") == "OST_Rooms"]
    if rooms:
        unplaced = sum(1 for r in rooms if not _is_placed(r))
        add("unplaced_rooms", 100 * (1 - unplaced / len(rooms)), {"rooms": len(rooms), "unplaced": unplaced})
    else:
        skip("unplaced_rooms", "The snapshot has no room elements.")

    # unused (purgeable) types
    nonsystem = [t for t in types if t.get("family_source") != "system"]
    by_uid: Dict[Any, int] = {}
    by_name: Dict[Any, int] = {}
    for e in elements:
        if e.get("type_uid"):
            by_uid[e["type_uid"]] = by_uid.get(e["type_uid"], 0) + 1
        elif e.get("family") and e.get("type_name"):
            key = (e["family"], e["type_name"])
            by_name[key] = by_name.get(key, 0) + 1

    def n_used(t: Dict[str, Any]) -> int:
        return by_uid.get(t.get("uid"), 0) + by_name.get((t.get("family"), t.get("type_name")), 0)

    if not types:
        skip("unused_types", "The snapshot has no type list.")
    elif partial:
        skip("unused_types", "The snapshot is a partial capture; unused types cannot be told from types that were not captured.")
    elif not any(n_used(t) for t in types):
        skip("unused_types", "No placed instances match the type list, so usage cannot be counted.")
    elif not nonsystem:
        skip("unused_types", "The snapshot has only system types.")
    else:
        unused = sum(1 for t in nonsystem if n_used(t) == 0)
        add("unused_types", 100 * (1 - unused / len(nonsystem)), {"types": len(nonsystem), "unused": unused})

    # completeness
    cells = pc.compute_cells(elements, None, COMPLETENESS_TOP_N)["rows"]
    total = sum(c["total"] for c in cells)
    if total:
        filled = sum(c["filled"] for c in cells)
        add("completeness", 100.0 * filled / total,
            {"cells": len(cells), "filled": filled, "total": total, "top_n_per_category": COMPLETENESS_TOP_N})
    else:
        skip("completeness", "No element carries any parameter.")

    weight = sum(c["weight"] for c in used)
    score = round(sum(c["weight"] * c["subscore"] for c in used) / weight, 1) if weight else None
    return {"score": score, "components": used, "excluded": excluded, "partial": partial,
            "element_count": len(elements)}


def _scan_document(workspace: Any, doc_guid: str) -> List[Dict[str, Any]]:
    """Every readable snapshot file in the workspace with this doc_guid, oldest first."""
    folder = Path(workspace.allowed_directories[0]) / "snapshots"
    found: List[Dict[str, Any]] = []
    if not folder.is_dir():
        return found
    for path in folder.glob("*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                head = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(head, dict) or ((head.get("source") or {}).get("doc_guid") or "") != doc_guid:
            continue
        taken = _changes._parse_time(head.get("taken_at"))
        estimated = taken is None
        if taken is None:
            taken = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        found.append({"snapshot_id": path.stem, "taken": taken, "time_estimated": estimated})
    found.sort(key=lambda r: (r["taken"], r["snapshot_id"]))
    return found


def _csv_text(points: List[Dict[str, Any]]) -> str:
    names = list(WEIGHTS)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["snapshot_id", "taken_at", "score", "delta", "comparable", "partial"] + names + ["excluded"])
    for p in points:
        subs = {c["name"]: c["subscore"] for c in p["components"]}
        writer.writerow([p["snapshot_id"], p["taken_at"], p["score"], p["delta"], p["comparable"], p["partial"]]
                        + [subs.get(n, "") for n in names] + ["; ".join(e["name"] for e in p["excluded"])])
    return out.getvalue()


class ModelHealthModule:
    def score(
        self,
        snapshot_id: str = "",
        rule_pack: str = "",
        include_trend: bool = True,
        max_points: int = DEFAULT_MAX_POINTS,
        csv_filename: str = "",
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        max_points = max(1, min(int(max_points or DEFAULT_MAX_POINTS), MAX_POINTS))
        data = rg._load_review_snapshot(snapshot_id, workspace)  # refuses mock data in bridge mode
        current = compute_components(data, rule_pack, workspace)
        doc_guid = (data["source"].get("doc_guid") or "")
        notes: List[str] = ["Higher is better. The score is a rough indicator built from the listed components, not a measure of file size or speed."]
        if data["is_mock"]:
            notes.append("MOCK data: generated sample, not a live Revit model.")
        if current["partial"]:
            notes.append("The snapshot is a partial capture: the score describes the captured elements only.")
        if current["excluded"]:
            notes.append("Inputs missing from this snapshot were left out of the score, not counted as 0: "
                         + ", ".join(e["name"] for e in current["excluded"]) + ".")

        trend: Dict[str, Any] = {"included": False}
        points: List[Dict[str, Any]] = []
        if include_trend:
            if data["is_mock"]:
                trend = {"included": True, "doc_guid": doc_guid, "points": [], "note": "Mock data is not saved, so there is no history."}
            elif not doc_guid:
                trend = {"included": True, "doc_guid": "", "points": [],
                         "note": "The snapshot has no document id (source.doc_guid), so snapshots of the same document cannot be found."}
            else:
                entries = _scan_document(workspace, doc_guid)
                total = len(entries)
                shown = entries[-max_points:]
                prev: Optional[Dict[str, Any]] = None
                if len(shown) < total:
                    notes.append(f"Trend shows the latest {len(shown)} of {total} snapshots of this document.")
                for e in shown:
                    sid = e["snapshot_id"]
                    loaded = data if sid == data["snapshot_id"] or sid == snapshot_id else rg._load_review_snapshot(sid, workspace)
                    res = current if loaded is data else compute_components(loaded, rule_pack, workspace)
                    point = {
                        "snapshot_id": sid, "taken_at": e["taken"].isoformat(), "time_estimated": e["time_estimated"],
                        "score": res["score"], "partial": res["partial"], "components": res["components"],
                        "excluded": res["excluded"], "delta": None, "comparable": False, "delta_note": "",
                    }
                    if prev is None:
                        point["delta_note"] = "First point."
                    elif prev["score"] is None or point["score"] is None:
                        point["delta_note"] = "A score is missing."
                    elif prev["partial"] or point["partial"]:
                        point["delta_note"] = "Not compared: a partial capture is involved."
                    elif [c["name"] for c in prev["components"]] != [c["name"] for c in point["components"]]:
                        point["delta_note"] = "Not compared: the two scores use different components."
                    else:
                        point["comparable"] = True
                        point["delta"] = round(point["score"] - prev["score"], 1)
                    points.append(point)
                    prev = point
                trend = {"included": True, "doc_guid": doc_guid, "snapshots_of_document": total, "points": points}
                if any(p["time_estimated"] for p in points):
                    notes.append("Some snapshots have no taken_at; their file time was used for ordering.")
        files: Dict[str, str] = {}
        if csv_filename:
            if not csv_filename.lower().endswith(".csv"):
                raise ValueError("csv_filename must end in .csv")
            if not points:
                points = [{"snapshot_id": data["snapshot_id"], "taken_at": data["taken_at"], "score": current["score"],
                           "delta": None, "comparable": False, "partial": current["partial"],
                           "components": current["components"], "excluded": current["excluded"]}]
            path = writable_path(workspace, rg._confined(workspace, csv_filename))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_csv_text(points), encoding="utf-8")
            files["csv_file"] = str(path)
        return {
            "read_only": True,
            "mock": data["is_mock"],
            "data_source": "MOCK DATA - generated sample, not your model." if data["is_mock"] else "Saved snapshot",
            "snapshot_id": data["snapshot_id"],
            "taken_at": data["taken_at"],
            "score": current["score"],
            "partial": current["partial"],
            "components": current["components"],
            "excluded": current["excluded"],
            "weights": WEIGHTS,
            "trend": trend,
            "notes": notes,
            **files,
        }
