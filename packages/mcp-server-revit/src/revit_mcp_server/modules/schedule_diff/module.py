"""
schedule_diff module - read-only comparison of the sheet list, sheet revisions and schedule rows
between two saved snapshots.

Command:
  compare - sheets added, removed, renumbered, renamed or moved in the numbering order; revision
            fields that changed; schedule rows added, removed, changed or moved. Optional CSV or
            Excel export of every difference.

Data read from a saved snapshot file:
  sheets     top-level list of {uid, number, name, params}, else ViewSheet element records.
             Revision fields are the sheet parameters whose name starts with "Current Revision".
  revisions  optional top-level list of {uid, number/sequence, description, date, issued}.
             The add-in does not capture it yet.
  schedules  optional top-level list of {uid, name, fields, rows, rows_truncated}; a row is
             {element_id, cells} with cells as {field: text} or a list in the order of fields.
             The add-in does not capture it yet (issue 367). Until it does, this block is reported
             as not captured. The row layout here is UNVERIFIED against a live Revit capture.

A block that either snapshot does not hold is reported as "not_captured". It is never reported
as "no change".
"""
from __future__ import annotations

import bisect
import csv
import importlib.util
import io
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from revit_mcp_server.security.module_permissions import writable_path
from revit_mcp_server.security.safe_paths import snapshot_file

DEFAULT_MAX_ITEMS = 200
REVISION_PARAM_PREFIX = "current revision"
EXPORT_HEADER = ["section", "schedule", "change", "key", "name", "field", "old", "new"]
LIST_KEYS = ("added", "removed", "changed", "moved")
_DIGITS = re.compile(r"(\d+)")


def _sibling(module_id: str) -> Any:
    """Load another module's module.py by file path (the server loads modules as plain modules)."""
    path = Path(__file__).resolve().parent.parent / module_id / "module.py"
    spec = importlib.util.spec_from_file_location(f"_schedule_diff_{module_id}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sva = _sibling("sheet_view_audit")


# ------------------------------------------------------------------ small helpers

def _text(value: Any) -> str:
    """Cell or parameter value as text; a parameter record {"v": value} gives its value."""
    if isinstance(value, dict) and "v" in value:
        value = value["v"]
    return "" if value is None else str(value).strip()


def _natural_key(number: Any) -> Tuple:
    parts = _DIGITS.split(str(number or "").strip().lower())
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in parts if p != "")


def moved_keys(old_order: List[str], new_order: List[str]) -> List[Tuple[str, int, int]]:
    """Keys that changed place between two orders of the same keys (1-based positions).

    Keys on a longest run that keeps its relative order are not moved; the rest are, so moving
    one item over many does not report all of them.
    """
    position = {k: i for i, k in enumerate(old_order)}
    seq = [position[k] for k in new_order]
    tails: List[int] = []      # smallest tail value of an increasing run of each length
    tail_at: List[int] = []    # index in seq of that tail
    prev = [-1] * len(seq)
    for i, v in enumerate(seq):
        j = bisect.bisect_left(tails, v)
        if j == len(tails):
            tails.append(v)
            tail_at.append(i)
        else:
            tails[j] = v
            tail_at[j] = i
        prev[i] = tail_at[j - 1] if j else -1
    keep = set()
    i = tail_at[-1] if tail_at else -1
    while i != -1:
        keep.add(i)
        i = prev[i]
    return [(new_order[i], seq[i] + 1, i + 1) for i in range(len(seq)) if i not in keep]


def _not_captured(what: str, older_has: bool, newer_has: bool, extra: str = "") -> Dict[str, Any]:
    if not older_has and not newer_has:
        where = "Neither snapshot holds"
    elif not older_has:
        where = "The older snapshot does not hold"
    else:
        where = "The newer snapshot does not hold"
    return {
        "status": "not_captured",
        "message": f"{where} {what}, so it was not compared. This is not a result of no change. {extra}".strip(),
    }


def _kv_changes(old: Dict[str, Any], new: Dict[str, Any], prefix: str) -> List[Dict[str, Any]]:
    out = []
    for name in sorted(set(old) | set(new), key=lambda n: str(n).lower()):
        a, b = _text(old.get(name)), _text(new.get(name))
        if a != b:
            out.append({"field": f"{prefix}{name}", "old": a, "new": b})
    return out


# ------------------------------------------------------------------ sheets

def _sheets_of(data: Dict[str, Any]) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    if isinstance(data.get("sheets"), list):
        return [s for s in data["sheets"] if isinstance(s, dict)], "top-level sheets list"
    derived, _ = sva.derive_from_elements(data.get("elements") or [])
    if derived:
        return derived, "ViewSheet element records"
    return None, ""


def _sheet_key(s: Dict[str, Any]) -> str:
    return str(s.get("uid") or "") or f"number:{_text(s.get('number'))}"


def _ref(s: Dict[str, Any]) -> Dict[str, Any]:
    return {"uid": s.get("uid"), "number": _text(s.get("number")), "name": _text(s.get("name"))}


_SHEET_IDENTITY_PARAMS = {"sheet number", "sheet name"}  # already compared as number and name


def _is_revision(name: Any) -> bool:
    return str(name).lower().startswith(REVISION_PARAM_PREFIX)


def diff_sheets(old: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> Dict[str, Any]:
    a = {_sheet_key(s): s for s in old}
    b = {_sheet_key(s): s for s in new}
    added = [_ref(b[k]) for k in b if k not in a]
    removed = [_ref(a[k]) for k in a if k not in b]
    changed: List[Dict[str, Any]] = []
    for k in b:
        if k not in a:
            continue
        sa, sb = a[k], b[k]
        changes: List[Dict[str, Any]] = []
        for field in ("number", "name"):
            if _text(sa.get(field)) != _text(sb.get(field)):
                changes.append({"field": field, "old": _text(sa.get(field)), "new": _text(sb.get(field))})
        pa, pb = sa.get("params") or {}, sb.get("params") or {}
        changes += _kv_changes({n: v for n, v in pa.items() if _is_revision(n)},
                               {n: v for n, v in pb.items() if _is_revision(n)}, "revision: ")
        changes += _kv_changes({n: v for n, v in pa.items() if not _is_revision(n) and str(n).lower() not in _SHEET_IDENTITY_PARAMS},
                               {n: v for n, v in pb.items() if not _is_revision(n) and str(n).lower() not in _SHEET_IDENTITY_PARAMS}, "param: ")
        if changes:
            changed.append({**_ref(sb), "changes": changes})

    common = [k for k in a if k in b]

    def order(src: Dict[str, Dict[str, Any]]) -> List[str]:
        return sorted(common, key=lambda x: (_natural_key(src[x].get("number")), x))

    moved = [{**_ref(b[k]), "from_position": f, "to_position": t} for k, f, t in moved_keys(order(a), order(b))]
    return {"added": added, "removed": removed, "changed": changed, "moved": moved}


# ------------------------------------------------------------------ revisions

def _rev_key(r: Dict[str, Any]) -> str:
    seq = r.get("sequence") if r.get("sequence") is not None else r.get("number")
    return str(r.get("uid") or "") or f"seq:{_text(seq)}"


def _rev_brief(r: Dict[str, Any]) -> Dict[str, Any]:
    return {k: r.get(k) for k in ("uid", "sequence", "number", "date", "description", "issued") if k in r}


def diff_revisions(old: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> Dict[str, Any]:
    a = {_rev_key(r): r for r in old}
    b = {_rev_key(r): r for r in new}
    changed = []
    for k in b:
        if k in a:
            ch = [c for c in _kv_changes(a[k], b[k], "") if c["field"] != "uid"]
            if ch:
                changed.append({**_rev_brief(b[k]), "changes": ch})
    return {
        "added": [_rev_brief(b[k]) for k in b if k not in a],
        "removed": [_rev_brief(a[k]) for k in a if k not in b],
        "changed": changed,
    }


# ------------------------------------------------------------------ schedules

def _schedules_of(data: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    block = data.get("schedules")
    return [s for s in block if isinstance(s, dict)] if isinstance(block, list) else None


def _sched_key(s: Dict[str, Any]) -> str:
    return str(s.get("uid") or "") or f"name:{_text(s.get('name'))}"


def _normal_rows(sched: Dict[str, Any]) -> Optional[List[Tuple[Optional[str], Dict[str, str]]]]:
    rows = sched.get("rows")
    if not isinstance(rows, list):
        return None
    fields = [str(f) for f in (sched.get("fields") or [])]
    out: List[Tuple[Optional[str], Dict[str, str]]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        cells = r.get("cells")
        if isinstance(cells, list):
            cells = {(fields[i] if i < len(fields) else f"column {i + 1}"): c for i, c in enumerate(cells)}
        eid = r.get("element_id", r.get("id"))
        out.append((None if eid in (None, "", -1) else str(eid),
                    {str(k): _text(v) for k, v in (cells or {}).items()}))
    return out


def _split_keyed(rows: List[Tuple[Optional[str], Dict[str, str]]]):
    counts = Counter(k for k, _ in rows if k is not None)
    keyed = {k: c for k, c in rows if k is not None and counts[k] == 1}
    unkeyed = [c for k, c in rows if k is None or counts[k] > 1]
    return keyed, [k for k, _ in rows if k in keyed], unkeyed


def _cells_tuple(cells: Dict[str, str]) -> Tuple:
    return tuple(sorted(cells.items()))


def diff_schedule_rows(old_rows, new_rows) -> Dict[str, Any]:
    ka, order_a, loose_a = _split_keyed(old_rows)
    kb, order_b, loose_b = _split_keyed(new_rows)
    added = [{"element_id": k, "cells": kb[k]} for k in order_b if k not in ka]
    removed = [{"element_id": k, "cells": ka[k]} for k in order_a if k not in kb]
    changed = []
    for k in order_b:
        if k in ka:
            ch = _kv_changes(ka[k], kb[k], "")
            if ch:
                changed.append({"element_id": k, "cells": kb[k], "changes": ch})
    common_a = [k for k in order_a if k in kb]
    common_b = [k for k in order_b if k in ka]
    moved = [{"element_id": k, "cells": kb[k], "from_position": f, "to_position": t}
             for k, f, t in moved_keys(common_a, common_b)]
    # Rows with no element id (or an id used twice) can only be matched by their cell text.
    left_a, left_b = Counter(map(_cells_tuple, loose_a)), Counter(map(_cells_tuple, loose_b))
    for cells in loose_b:
        t = _cells_tuple(cells)
        if left_a[t] > 0:
            left_a[t] -= 1
        else:
            added.append({"element_id": None, "cells": cells})
    for cells in loose_a:
        t = _cells_tuple(cells)
        if left_b[t] > 0:
            left_b[t] -= 1
        else:
            removed.append({"element_id": None, "cells": cells})
    return {"added": added, "removed": removed, "changed": changed, "moved": moved}


def _sched_brief(s: Dict[str, Any]) -> Dict[str, Any]:
    return {"uid": s.get("uid"), "name": _text(s.get("name"))}


def diff_schedules(old: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> Dict[str, Any]:
    a = {_sched_key(s): s for s in old}
    b = {_sched_key(s): s for s in new}
    per: List[Dict[str, Any]] = []
    for k in b:
        if k not in a:
            continue
        sa, sb = a[k], b[k]
        ra, rb = _normal_rows(sa), _normal_rows(sb)
        item: Dict[str, Any] = _sched_brief(sb)
        if _text(sa.get("name")) != _text(sb.get("name")):
            item["renamed_from"] = _text(sa.get("name"))
        fa, fb = [str(f) for f in sa.get("fields") or []], [str(f) for f in sb.get("fields") or []]
        if fa != fb:
            item["fields_added"] = [f for f in fb if f not in fa]
            item["fields_removed"] = [f for f in fa if f not in fb]
        if ra is None or rb is None:
            item["rows"] = "not_captured"
        else:
            item["rows"] = "compared"
            item.update(diff_schedule_rows(ra, rb))
            if any(s.get("rows_truncated") or s.get("truncated") for s in (sa, sb)):
                item["rows_cut_short"] = True
        interesting = ("renamed_from", "fields_added", "fields_removed", "rows_cut_short", *LIST_KEYS)
        if item["rows"] == "not_captured" or any(item.get(n) for n in interesting):
            per.append(item)
    return {
        "schedules_added": [_sched_brief(b[k]) for k in b if k not in a],
        "schedules_removed": [_sched_brief(a[k]) for k in a if k not in b],
        "schedules": per,
        "schedules_compared": sum(1 for k in b if k in a),
    }


# ------------------------------------------------------------------ output

def _csv_cell(v: Any) -> Any:
    # A leading = + - @ would be run as a formula by a spreadsheet; the text comes from the model.
    return "'" + v if isinstance(v, str) and v[:1] in "=+-@" else v


def _export_rows(sheets: Dict[str, Any], revisions: Dict[str, Any], schedules: Dict[str, Any]) -> List[List[Any]]:
    rows: List[List[Any]] = []

    def add(section, schedule, change, key, name, field="", old="", new=""):
        rows.append([section, schedule, change, key, name, field, old, new])

    if sheets.get("status") == "compared":
        for s in sheets["added"]:
            add("sheets", "", "added", s["number"], s["name"])
        for s in sheets["removed"]:
            add("sheets", "", "removed", s["number"], s["name"])
        for s in sheets["changed"]:
            for c in s["changes"]:
                add("sheets", "", "changed", s["number"], s["name"], c["field"], c["old"], c["new"])
        for s in sheets["moved"]:
            add("sheets", "", "moved", s["number"], s["name"], "position", s["from_position"], s["to_position"])
    if revisions.get("status") == "compared":
        for kind in ("added", "removed"):
            for r in revisions[kind]:
                add("revisions", "", kind, r.get("sequence", r.get("number", "")), r.get("description", ""))
        for r in revisions["changed"]:
            for c in r["changes"]:
                add("revisions", "", "changed", r.get("sequence", r.get("number", "")), r.get("description", ""),
                    c["field"], c["old"], c["new"])
    if schedules.get("status") in ("compared", "partial"):
        for s in schedules["schedules_added"]:
            add("schedules", s["name"], "schedule added", "", s["name"])
        for s in schedules["schedules_removed"]:
            add("schedules", s["name"], "schedule removed", "", s["name"])
        for sc in schedules["schedules"]:
            name = sc["name"]
            if sc.get("renamed_from"):
                add("schedules", name, "schedule renamed", "", name, "name", sc["renamed_from"], name)
            for f in sc.get("fields_added", []):
                add("schedules", name, "field added", "", f)
            for f in sc.get("fields_removed", []):
                add("schedules", name, "field removed", "", f)
            for kind in ("added", "removed"):
                for r in sc.get(kind, []):
                    add("schedules", name, f"row {kind}", r["element_id"] or "", "; ".join(r["cells"].values()))
            for r in sc.get("changed", []):
                for c in r["changes"]:
                    add("schedules", name, "row changed", r["element_id"], "", c["field"], c["old"], c["new"])
            for r in sc.get("moved", []):
                add("schedules", name, "row moved", r["element_id"], "", "position",
                    r["from_position"], r["to_position"])
    return rows


def _write_export(workspace: Any, filename: str, rows: List[List[Any]]) -> str:
    rg = _sibling("report_generator")
    out = writable_path(workspace, rg._confined(workspace, filename))
    out.parent.mkdir(parents=True, exist_ok=True)
    safe = [[_csv_cell(v) for v in r] for r in rows]
    if filename.lower().endswith(".csv"):
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(EXPORT_HEADER)
        writer.writerows(safe)
        out.write_text(buf.getvalue(), encoding="utf-8")
    else:
        wb = rg._workbook()
        ws = wb.active
        ws.title = "Differences"
        ws.append(EXPORT_HEADER)
        for r in safe:
            ws.append(r)
        wb.save(str(out))
    return str(out)


def _load(workspace: Any, snapshot_id: Any) -> Dict[str, Any]:
    path = snapshot_file(Path(workspace.allowed_directories[0]) / "snapshots", snapshot_id)
    if not path.exists():
        raise ValueError(f"Snapshot '{snapshot_id}' not found.")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise ValueError(f"Snapshot '{snapshot_id}' could not be read: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"Snapshot '{snapshot_id}' does not hold a JSON object.")
    return data


def _partial_capture(data: Dict[str, Any]) -> bool:
    counts = data.get("counts") or {}
    return bool(counts.get("sheets_truncated") or counts.get("truncated") or counts.get("categories")
                or counts.get("dirty_only") or data.get("dirty_only"))


def _cap_lists(section: Dict[str, Any], keys: Tuple[str, ...], limit: int) -> bool:
    cut = False
    for key in keys:
        if isinstance(section.get(key), list) and len(section[key]) > limit:
            section[key] = section[key][:limit]
            cut = True
    return cut


class ScheduleDiffModule:
    def compare(
        self,
        older_snapshot_id: str = "",
        newer_snapshot_id: str = "",
        max_items: int = DEFAULT_MAX_ITEMS,
        export_filename: str = "",
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        if not older_snapshot_id or not newer_snapshot_id:
            raise ValueError("schedule_diff_compare needs older_snapshot_id and newer_snapshot_id. "
                             "Take two snapshots first and pass their ids.")
        try:
            limit = DEFAULT_MAX_ITEMS if max_items is None else int(max_items)
        except (TypeError, ValueError):
            raise ValueError("max_items must be a whole number.") from None
        if not 1 <= limit <= 5000:
            raise ValueError("max_items must be between 1 and 5000.")
        if export_filename and not (isinstance(export_filename, str)
                                    and export_filename.lower().endswith((".csv", ".xlsx"))):
            raise ValueError("export_filename must end in .csv or .xlsx")

        old, new = _load(workspace, older_snapshot_id), _load(workspace, newer_snapshot_id)

        sheets_a, src_a = _sheets_of(old)
        sheets_b, src_b = _sheets_of(new)
        if sheets_a is None or sheets_b is None:
            sheets: Dict[str, Any] = _not_captured(
                "sheet records", sheets_a is not None, sheets_b is not None,
                "Take a full snapshot of a project that has sheets.")
        else:
            d = diff_sheets(sheets_a, sheets_b)
            sheets = {"status": "compared", "data_source": src_b if src_a == src_b else f"{src_a} / {src_b}",
                      "sheets_older": len(sheets_a), "sheets_newer": len(sheets_b),
                      "counts": {k: len(v) for k, v in d.items()}, **d}

        revs_a = old.get("revisions") if isinstance(old.get("revisions"), list) else None
        revs_b = new.get("revisions") if isinstance(new.get("revisions"), list) else None
        if revs_a is None or revs_b is None:
            revisions: Dict[str, Any] = _not_captured(
                "a revision list", revs_a is not None, revs_b is not None,
                "Revision fields on each sheet are listed under sheets, marked 'revision:'.")
        else:
            rd = diff_revisions([r for r in revs_a if isinstance(r, dict)], [r for r in revs_b if isinstance(r, dict)])
            revisions = {"status": "compared", "counts": {k: len(v) for k, v in rd.items()}, **rd}

        sch_a, sch_b = _schedules_of(old), _schedules_of(new)
        if sch_a is None or sch_b is None:
            schedules: Dict[str, Any] = _not_captured(
                "schedule rows", sch_a is not None, sch_b is not None,
                "The add-in does not capture schedule rows yet (issue 367).")
        else:
            sd = diff_schedules(sch_a, sch_b)
            cut = any(s.get("rows_cut_short") for s in sd["schedules"])
            not_cap = [s["name"] for s in sd["schedules"] if s["rows"] == "not_captured"]
            schedules = {
                "status": "partial" if cut or not_cap else "compared",
                "schedules_compared": sd["schedules_compared"],
                "counts": {
                    "schedules_added": len(sd["schedules_added"]),
                    "schedules_removed": len(sd["schedules_removed"]),
                    **{k: sum(len(s.get(k, [])) for s in sd["schedules"]) for k in LIST_KEYS},
                },
                **sd,
            }
            note = []
            if cut:
                note.append("Some schedules were cut short at capture, so rows missing from them "
                            "may not have been removed.")
            if not_cap:
                note.append("Rows were not captured for: " + ", ".join(not_cap) + ".")
            if note:
                schedules["message"] = " ".join(note)

        export_rows = _export_rows(sheets, revisions, schedules)

        truncated = _cap_lists(sheets, LIST_KEYS, limit) | _cap_lists(revisions, LIST_KEYS, limit)
        truncated |= _cap_lists(schedules, ("schedules_added", "schedules_removed", "schedules"), limit)
        for sc in schedules.get("schedules", []):
            truncated |= _cap_lists(sc, LIST_KEYS, limit)

        messages: List[str] = []
        missing = [n for n, s in (("sheets", sheets), ("revisions", revisions), ("schedules", schedules))
                   if s["status"] == "not_captured"]
        status = "ok"
        if missing:
            status = "partial"
            messages.append("Not captured, so not compared: " + ", ".join(missing)
                            + ". Details are in each section. Missing data is not a result of no change.")
        if schedules["status"] == "partial":
            status = "partial"
            messages.append(schedules.get("message", ""))
        if _partial_capture(old) or _partial_capture(new):
            status = "partial"
            messages.append("A snapshot was truncated, category-filtered or dirty-only; "
                            "added and removed items may only reflect what was captured.")
        if len(missing) == 3:
            status = "no_data"
        if truncated:
            messages.append(f"Lists are cut at {limit} rows; counts are complete. Use export_filename for every row.")

        result: Dict[str, Any] = {
            "read_only": True,
            "status": status,
            "message": " ".join(m for m in messages if m) or "Every block was compared.",
            "older_snapshot_id": older_snapshot_id,
            "newer_snapshot_id": newer_snapshot_id,
            "sheets": sheets,
            "revisions": revisions,
            "schedules": schedules,
            "difference_rows": len(export_rows),
        }
        if export_filename:
            result["export_file"] = _write_export(workspace, export_filename, export_rows)
        return result
