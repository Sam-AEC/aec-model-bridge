"""
warnings_triage module — read-only triage of Revit warnings.

Command:
  review_warnings — Group warnings by type, rank by elements touched, flag the
                    coordinator-relevant families, suggest a next step per group.

Data path (nothing new is needed on the Revit side):
  The Revit add-in already exposes ``revit.get_warnings`` (tool
  ``revit_get_warnings``), returning ``{"warnings": [{"description", "severity",
  "failing_elements": [<Revit element id>, ...]}], "count": N}``. The model
  snapshot does NOT carry warnings. Revit returns numeric element ids, so they
  are mapped to UniqueIds through the snapshot (if a ``snapshot_id`` is given).
  Without a snapshot the numeric ids are returned and ``unique_ids_available``
  is false.

Fetching live warnings needs a running Revit with the add-in: UNVERIFIED here.
"""
from __future__ import annotations

import json
import re
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

# (family key, label, regex on lowercase description, plain next step)
_FAMILIES: List[Tuple[str, str, str, str]] = [
    (
        "duplicate_mark",
        "Duplicate Mark values",
        r"duplicate.*(mark|number)|(mark|number).*duplicate|same (mark|number)",
        "Give each listed element its own Mark (or Number). Ask the model owner to renumber, "
        "then run Review Revit Warnings again.",
    ),
    (
        "overlapping_elements",
        "Overlapping or identical elements",
        r"overlap|identical instances|same place|duplicate (instance|element)",
        "Open the listed elements in Revit and delete or move the extra copy. "
        "Overlaps are often a double-placed or copied element, so tell the model owner.",
    ),
    (
        "room_not_enclosed",
        "Room not enclosed",
        r"room.*(not (in a )?(properly )?enclosed|redundant|not placed)|not in a properly enclosed|enclosed region",
        "Close the gap in the walls or add a Room Separation line around each listed room. "
        "Until then, room areas and numbers in schedules are wrong.",
    ),
]

_GENERIC_STEPS = [
    (r"off axis|slightly off", "Straighten the listed elements in Revit (they are a hair off the grid or axis) so they stop causing small clashes."),
    (r"join|joined|cut", "Check the listed elements' joins in Revit and unjoin or re-join them."),
    (r"tag|outside of its room|not (visible|placed)", "Move or delete the listed tags and annotations so they match the model."),
    (r"line|sketch", "Fix or delete the stray line in the listed elements' sketch."),
]
_DEFAULT_STEP = (
    "Open one listed element in Revit to read the full message, then fix it or hand it to the model owner."
)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _classify(description: str) -> Tuple[str, str, str, bool]:
    low = _normalise(description).lower()
    for key, label, pattern, step in _FAMILIES:
        if re.search(pattern, low):
            return key, label, step, True
    for pattern, step in _GENERIC_STEPS:
        if re.search(pattern, low):
            return "other", "", step, False
    return "other", "", _DEFAULT_STEP, False


def _snapshot_id_map(snapshot_id: str, workspace: Any) -> Dict[int, str]:
    if not snapshot_id or workspace is None:
        return {}
    path = workspace.allowed_directories[0] / "snapshots" / f"{snapshot_id}.json"
    if not path.exists():
        raise ValueError(f"Snapshot '{snapshot_id}' not found.")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        int(el["element_id"]): el["uid"]
        for el in data.get("elements", [])
        if el.get("uid") is not None and el.get("element_id") is not None
    }


def group_warnings(
    warnings: List[Dict[str, Any]],
    id_to_uid: Optional[Dict[int, str]] = None,
    max_elements_per_group: int = 50,
) -> List[Dict[str, Any]]:
    """Pure grouping/ranking logic (no Revit needed)."""
    id_to_uid = id_to_uid or {}
    groups: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    for w in warnings:
        desc = _normalise(w.get("description", "")) or "(no description)"
        g = groups.setdefault(
            desc.lower(),
            {"description": desc, "severities": set(), "warning_count": 0, "ids": []},
        )
        g["warning_count"] += 1
        if w.get("severity"):
            g["severities"].add(str(w["severity"]))
        for raw in w.get("failing_elements") or []:
            if raw not in g["ids"]:
                g["ids"].append(raw)

    out: List[Dict[str, Any]] = []
    for g in groups.values():
        key, label, step, coord = _classify(g["description"])
        uids: List[str] = []
        unmapped: List[Any] = []
        for raw in g["ids"]:
            if isinstance(raw, str) and not raw.lstrip("-").isdigit():
                uids.append(raw)  # already a UniqueId
                continue
            try:
                uid = id_to_uid.get(int(raw))
            except (TypeError, ValueError):
                uid = None
            if uid:
                uids.append(uid)
            else:
                unmapped.append(raw)
        out.append({
            "description": g["description"],
            "family": key,
            "family_label": label or None,
            "coordinator_relevant": coord,
            "severity": sorted(g["severities"]),
            "warning_count": g["warning_count"],
            "elements_affected": len(g["ids"]),
            "element_unique_ids": uids[:max_elements_per_group],
            "element_ids_without_unique_id": unmapped[:max_elements_per_group],
            "element_list_truncated": len(g["ids"]) > max_elements_per_group,
            "next_step": step,
        })
    out.sort(key=lambda r: (-r["elements_affected"], -r["warning_count"], r["description"]))
    for rank, row in enumerate(out, 1):
        row["rank"] = rank
    return out


class WarningsTriageModule:

    def review_warnings(
        self,
        snapshot_id: str = "",
        coordinator_only: bool = False,
        top: int = 25,
        max_elements_per_group: int = 50,
        workspace: Any = None,
        tool_executor: Any = None,
        warnings: Optional[List[Dict[str, Any]]] = None,
        **_,
    ) -> Dict[str, Any]:
        notes: List[str] = []
        if warnings is None:
            if tool_executor is None:
                return {
                    "ok": False,
                    "error": "Could not read warnings: no connection to Revit tools in this session.",
                    "missing_data": (
                        "Revit warnings. The model snapshot does not include them; they come "
                        "live from Revit via the revit_get_warnings tool (needs Revit open "
                        "with the add-in running)."
                    ),
                }
            raw = tool_executor("revit_get_warnings", {})
            if isinstance(raw, dict) and isinstance(raw.get("data"), dict) and "warnings" not in raw:
                raw = raw["data"]
            warnings = (raw or {}).get("warnings") or []
        id_to_uid = _snapshot_id_map(snapshot_id, workspace)
        if not snapshot_id:
            notes.append(
                "No snapshot_id given, so elements are listed by Revit element id. "
                "Pass a snapshot_id to get UniqueIds."
            )
        elif warnings and not id_to_uid:
            notes.append("The snapshot has no elements to match against.")

        all_groups = group_warnings(warnings, id_to_uid, max(1, int(max_elements_per_group)))
        groups = [g for g in all_groups if g["coordinator_relevant"]] if coordinator_only else all_groups
        groups = groups[: max(1, int(top))]
        for rank, g in enumerate(groups, 1):
            g["rank"] = rank
        if snapshot_id and any(g["element_ids_without_unique_id"] for g in groups):
            notes.append(
                "Some element ids are not in the snapshot (take a fresh snapshot) and are listed by Revit id."
            )

        return {
            "ok": True,
            "read_only": True,
            "total_warnings": len(warnings),
            "total_groups": len(all_groups),
            "coordinator_groups": sum(1 for g in all_groups if g["coordinator_relevant"]),
            "unique_ids_available": bool(id_to_uid),
            "groups": groups,
            "notes": notes,
        }
