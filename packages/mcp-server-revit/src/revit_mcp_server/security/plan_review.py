"""Read-only review aids for a plan: a before/after preview and a blast-radius estimate.

Both are computed from the plan's stored actions (and, for categories, levels and worksets,
from the snapshot the plan names) every time a plan is shown. Nothing here is stored on the
plan, so it never changes the plan hash, and nothing here approves or runs anything. A value
that is not known is reported as "unknown"; it is never guessed.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import file_binding
from . import proof as proof_mod
from ..script_lint import lint_script

UNKNOWN = "unknown"
EMPTY_TEXT = "(empty)"
NOT_CAPTURED_TEXT = "(not captured)"

PREVIEW_MAX_ROWS = 100        # rows kept in the structured preview
MARKDOWN_MAX_ROWS = 25        # rows shown in preview_markdown
CELL_MAX_CHARS = 60
GEOMETRY_MAX_BOXES = 200      # bounding boxes kept for the inline 3D view

# Risk thresholds. A plan takes the highest level any rule gives it.
#   low:    at most 10 elements and at most 5 actions
#   medium: more than that, up to 100 elements and 25 actions
#   high:   more than 100 elements or more than 25 actions
# A plan also rises to at least medium when an action names no element (its reach is not
# known) or when a tool name says it deletes, purges or removes.
RISK_LOW_MAX_ELEMENTS = 10
RISK_LOW_MAX_ACTIONS = 5
RISK_MEDIUM_MAX_ELEMENTS = 100
RISK_MEDIUM_MAX_ACTIONS = 25
DESTRUCTIVE_WORDS = ("delete", "purge", "remove")

_ID_KEYS = ID_KEYS = ("element_id", "elementId")
_ID_LIST_KEYS = ID_LIST_KEYS = ("element_ids", "elementIds", "ids")
_UID_KEYS = ("element_uid", "unique_id", "uniqueId", "uid")
_UID_LIST_KEYS = ("element_uids", "unique_ids", "uids")
_FIELD_KEYS = {
    "category": ("category", "category_name", "built_in_category"),
    "level": ("level", "level_name", "level_id", "level_uid"),
    "workset": ("workset", "workset_name", "workset_id"),
}


def _scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float)) and not isinstance(value, bool)


def _first(args: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[str]:
    for key in keys:
        value = args.get(key)
        if _scalar(value) and str(value).strip() != "":
            return str(value)
    return None


def _listed(args: Dict[str, Any], keys: Tuple[str, ...]) -> List[str]:
    for key in keys:
        value = args.get(key)
        if isinstance(value, list):
            return [str(v) for v in value if _scalar(v)]
    return []


def element_ids_of(args: Dict[str, Any]) -> List[str]:
    """Element ids an action's arguments name (single or list form), in order, de-duplicated."""
    if not isinstance(args, dict):
        return []
    ids = _listed(args, _ID_LIST_KEYS)
    single = _first(args, _ID_KEYS)
    if single is not None:
        ids.insert(0, single)
    return list(dict.fromkeys(ids))


def _uids(args: Dict[str, Any]) -> List[str]:
    out = _listed(args, _UID_LIST_KEYS)
    single = _first(args, _UID_KEYS)
    if single is not None:
        out.insert(0, single)
    return out


def action_args(action: Dict[str, Any]) -> Dict[str, Any]:
    """The 'after' side of an action's diff, falling back to its arguments."""
    diff = action.get("diff") if isinstance(action.get("diff"), dict) else {}
    if isinstance(diff.get("after"), dict):
        return diff["after"]
    return action.get("arguments") if isinstance(action.get("arguments"), dict) else {}


def snapshot_index(workspace_dir: Optional[Path], snapshot_id: Optional[str]) -> Dict[str, Dict[str, Any]]:
    """element_id -> {uid, category, level, workset} for the plan's snapshot; {} when there is
    none or it cannot be read. Only fields the snapshot actually holds are returned."""
    if not workspace_dir or not snapshot_id:
        return {}
    try:
        with open(proof_mod.snapshot_file(Path(workspace_dir) / "snapshots", snapshot_id), "r", encoding="utf-8") as f:
            snap = json.load(f)
        index: Dict[str, Dict[str, Any]] = {}
        for el in snap.get("elements", []):
            if not isinstance(el, dict) or el.get("element_id") is None:
                continue
            info: Dict[str, Any] = {}
            if el.get("uid"):
                info["uid"] = str(el["uid"])
            for field, keys in (("category", ("category",)),
                                ("level", ("level", "level_name", "level_uid")),
                                ("workset", ("workset", "workset_name"))):
                for key in keys:
                    if el.get(key) not in (None, ""):
                        info[field] = str(el[key])
                        break
            index[str(el["element_id"])] = info
        return index
    except Exception:  # noqa: BLE001 - a missing snapshot only means more "unknown"
        return {}


def _box_of(el: Dict[str, Any]) -> Optional[Dict[str, List[float]]]:
    """The element's snapshot ``bbox`` as {min, max} of three finite numbers each, else None."""
    box = el.get("bbox")
    if not isinstance(box, dict):
        return None
    lo, hi = box.get("min"), box.get("max")
    if not (isinstance(lo, list) and isinstance(hi, list) and len(lo) == 3 and len(hi) == 3):
        return None
    out = []
    for side in (lo, hi):
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in side):
            return None
        out.append([float(v) for v in side])
    if any(a > b for a, b in zip(out[0], out[1])):
        return None
    return {"min": out[0], "max": out[1]}


def affected_boxes(plan: Dict[str, Any], workspace_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Bounding boxes of the elements the plan names, read from the plan's snapshot.

    Feeds the read-only 3D view. Returns None when there is no readable snapshot or no named element
    has a valid box; nothing is guessed. Boxes are in the units the snapshot holds; the view does not
    convert them. ``without_box`` counts named elements that have no usable box. Never raises."""
    try:
        snapshot_id = plan.get("snapshot_id")
        if not workspace_dir or not snapshot_id:
            return None
        with open(proof_mod.snapshot_file(Path(workspace_dir) / "snapshots", snapshot_id), "r", encoding="utf-8") as f:
            snap = json.load(f)
        ids: Dict[str, None] = {}
        uids: Dict[str, None] = {}
        for action in plan.get("actions", []) or []:
            if isinstance(action, dict):
                args = action_args(action)
                ids.update(dict.fromkeys(element_ids_of(args)))
                uids.update(dict.fromkeys(_uids(args)))
        by_id: Dict[str, Dict[str, Any]] = {}
        by_uid: Dict[str, Dict[str, Any]] = {}
        for el in snap.get("elements", []):
            if not isinstance(el, dict):
                continue
            if el.get("element_id") is not None:
                by_id[str(el["element_id"])] = el
            if el.get("uid"):
                by_uid[str(el["uid"])] = el
        chosen: Dict[int, Dict[str, Any]] = {}
        unresolved = 0
        for key, table in ((ids, by_id), (uids, by_uid)):
            for name in key:
                el = table.get(name)
                if el is None:
                    unresolved += 1
                else:
                    chosen.setdefault(id(el), el)
        boxes = []
        for el in chosen.values():
            box = _box_of(el)
            if box is not None:
                boxes.append({
                    "element_id": el.get("element_id"), "uid": el.get("uid"),
                    "category": el.get("category"), "name": el.get("name"), **box,
                })
        if not boxes:
            return None
        return {
            "source": f"snapshot {snapshot_id}",
            "unit": "snapshot units (not converted)",
            "boxes": boxes[:GEOMETRY_MAX_BOXES],
            "boxes_omitted": max(0, len(boxes) - GEOMETRY_MAX_BOXES),
            "without_box": unresolved + len(chosen) - len(boxes),
        }
    except Exception:  # noqa: BLE001 - the 3D view is optional
        return None


def _cell(value: Any) -> str:
    if value is None or value == "":
        return EMPTY_TEXT
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    text = " ".join(text.split())
    return text if len(text) <= CELL_MAX_CHARS else text[: CELL_MAX_CHARS - 3] + "..."


def _after_text(args: Dict[str, Any]) -> str:
    if "parameter_name" in args:
        return _cell(args.get("value"))
    skip = set(_ID_KEYS + _ID_LIST_KEYS + _UID_KEYS + _UID_LIST_KEYS + ("plan_id",))
    rest = {k: v for k, v in args.items() if k not in skip}
    return _cell(rest) if rest else EMPTY_TEXT


def preview_rows(plan: Dict[str, Any], index: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """One row per (action, element), from each action's stored ``diff``."""
    index = index or {}
    rows: List[Dict[str, Any]] = []
    for action in plan.get("actions", []) or []:
        if not isinstance(action, dict):
            continue
        diff = action.get("diff") if isinstance(action.get("diff"), dict) else {}
        after = action_args(action)
        before = diff.get("before") if isinstance(diff.get("before"), dict) else {}
        param = after.get("parameter_name") if _scalar(after.get("parameter_name")) else None
        ids = element_ids_of(after)
        uids = _uids(after)
        targets: List[Tuple[Optional[str], Optional[str]]] = []
        for i, eid in enumerate(ids):
            uid = uids[i] if len(uids) == len(ids) else (uids[0] if len(ids) == 1 and uids else None)
            targets.append((eid, uid or (index.get(eid) or {}).get("uid")))
        if not targets:
            targets = [(None, uids[0] if uids else None)]
        for eid, uid in targets:
            captured = False
            before_value: Any = None
            if eid is not None and param is not None and isinstance(before.get(eid), dict) and param in before[eid]:
                captured, before_value = True, before[eid][param]
            rows.append({
                "action_id": action.get("action_id"),
                "tool": action.get("tool"),
                "element_id": eid,
                "unique_id": uid,
                "parameter": param,
                "before": _cell(before_value) if captured else NOT_CAPTURED_TEXT,
                "after": _after_text(after),
            })
    return rows


def blast_radius(plan: Dict[str, Any], index: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Counts and risk for a plan. ``element_count`` is the number of distinct elements the
    actions name; ``unidentified_actions`` counts actions that name none (their reach is not
    known, so the count is a lower bound and risk is at least medium)."""
    index = index or {}
    actions = [a for a in (plan.get("actions", []) or []) if isinstance(a, dict)]
    elements: Dict[str, None] = {}
    found: Dict[str, set] = {"category": set(), "level": set(), "workset": set()}
    unknown = {"category": False, "level": False, "workset": False}
    unidentified = 0
    destructive = False
    for action in actions:
        args = action_args(action)
        tool = str(action.get("tool") or "").lower()
        destructive = destructive or any(w in tool for w in DESTRUCTIVE_WORDS)
        ids = element_ids_of(args)
        if not ids:
            unidentified += 1
        elements.update(dict.fromkeys(ids))
        for field, keys in _FIELD_KEYS.items():
            given = _first(args, keys)
            if given:
                found[field].add(given)
                continue
            for eid in ids:
                value = (index.get(eid) or {}).get(field)
                if value:
                    found[field].add(value)
                else:
                    unknown[field] = True
            if not ids:
                unknown[field] = True
    n_elements, n_actions = len(elements), len(actions)
    if n_elements > RISK_MEDIUM_MAX_ELEMENTS or n_actions > RISK_MEDIUM_MAX_ACTIONS:
        risk = "high"
    elif (n_elements > RISK_LOW_MAX_ELEMENTS or n_actions > RISK_LOW_MAX_ACTIONS
          or unidentified or destructive):
        risk = "medium"
    else:
        risk = "low"

    def listed(field: str) -> List[str]:
        out = sorted(found[field])
        return out + [UNKNOWN] if (unknown[field] or not out) else out

    return {
        "element_count": n_elements,
        "action_count": n_actions,
        "unidentified_actions": unidentified,
        "categories": listed("category"),
        "levels": listed("level"),
        "worksets": listed("workset"),
        "risk": risk,
    }


def _md_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def preview_markdown(rows: List[Dict[str, Any]], radius: Dict[str, Any], max_rows: int = MARKDOWN_MAX_ROWS) -> str:
    """A header with the blast radius and a table of at most ``max_rows`` rows."""
    header = (
        f"**Risk: {radius['risk']}** - {radius['element_count']} element(s), {radius['action_count']} action(s). "
        f"Categories: {', '.join(radius['categories'])}. Levels: {', '.join(radius['levels'])}. "
        f"Worksets: {', '.join(radius['worksets'])}."
    )
    if radius.get("unidentified_actions"):
        header += f" {radius['unidentified_actions']} action(s) name no element, so the element count is a lower bound."
    lines = [" ".join(header.split()), "", "| Element | UniqueId | Parameter | Before | After | Tool |",
             "| --- | --- | --- | --- | --- | --- |"]
    for row in rows[:max_rows]:
        lines.append("| " + " | ".join(_md_cell(v) for v in (
            row["element_id"] if row["element_id"] is not None else UNKNOWN,
            row["unique_id"] or UNKNOWN,
            row["parameter"] or "-",
            row["before"], row["after"], row["tool"])) + " |")
    if not rows:
        lines.append("| (no actions) | | | | | |")
    if len(rows) > max_rows:
        lines.extend(["", f"{len(rows) - max_rows} more row(s) not shown."])
    return "\n".join(lines)


def bound_files(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The files whose content the plan binds (security/file_binding.py): path, sha256 and rows."""
    out: List[Dict[str, Any]] = []
    for action in plan.get("actions", []) or []:
        if isinstance(action, dict):
            shown = file_binding.preview(action.get("tool"), action.get("arguments"))
            if shown is not None:
                out.append({"action_id": action.get("action_id"), "tool": action.get("tool"), **shown})
    return out


def _bound_files_markdown(files: List[Dict[str, Any]]) -> List[str]:
    lines = []
    for f in files:
        rows = f" ({f['rows']} rows)" if "rows" in f else ""
        lines.append(f"Bound file for {_md_cell(f['tool'])}: {_md_cell(f['path'])}{rows}, {_md_cell(f['sha256'])}. "
                     "A different file content at run time is refused.")
    return lines


def script_lint_warnings(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Advisory lint warnings (script_lint.py) for each revit_execute_python action. They never block a plan."""
    out: List[Dict[str, Any]] = []
    for action in plan.get("actions", []) or []:
        if isinstance(action, dict) and action.get("tool") == "revit_execute_python":
            args = action.get("arguments")
            for warning in lint_script(args.get("script") if isinstance(args, dict) else None):
                out.append({"action_id": action.get("action_id"), **warning})
    return out


def _script_lint_markdown(warnings: List[Dict[str, Any]]) -> List[str]:
    lines = ["Script lint (advisory, does not block): known Revit API traps found in the script text."]
    for w in warnings:
        lines.append(f"- {_md_cell(w['rule'])} (line {w['line']}): {_md_cell(w['message'])}")
    return lines


def review_aids(plan: Dict[str, Any], workspace_dir: Optional[Path] = None) -> Dict[str, Any]:
    """``preview``, ``preview_markdown`` and ``blast_radius`` for one plan. Never raises:
    on an internal error the plan is shown without them rather than failing the listing."""
    try:
        index = snapshot_index(workspace_dir, plan.get("snapshot_id"))
        rows = preview_rows(plan, index)
        radius = blast_radius(plan, index)
        aids: Dict[str, Any] = {
            "preview": {"rows": rows[:PREVIEW_MAX_ROWS], "row_count": len(rows),
                        "rows_omitted": max(0, len(rows) - PREVIEW_MAX_ROWS)},
            "preview_markdown": preview_markdown(rows, radius),
            "blast_radius": radius,
        }
        files = bound_files(plan)
        if files:
            aids["bound_files"] = files
            aids["preview_markdown"] += "\n\n" + "\n".join(_bound_files_markdown(files))
        lint = script_lint_warnings(plan)
        if lint:
            aids["script_lint"] = lint
            aids["preview_markdown"] += "\n\n" + "\n".join(_script_lint_markdown(lint))
        return aids
    except Exception:  # noqa: BLE001
        return {}


def with_review_aids(plan: Any, workspace_dir: Optional[Path] = None) -> Any:
    if not isinstance(plan, dict):
        return plan
    return {**plan, **review_aids(plan, workspace_dir)}
