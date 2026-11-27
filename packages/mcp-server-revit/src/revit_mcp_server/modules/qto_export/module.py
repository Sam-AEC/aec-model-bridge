"""
qto_export module - quantity take-off from a saved snapshot to CSV and BC3.

Command:
  run - Count elements and sum Length, Area and Volume per category and type. Optional CSV
        and BC3 (FIEBDC-3) files are written inside the workspace.

Read-only: nothing in the model is changed. The files are written to the workspace only.
There are no prices; BC3 concepts carry an empty price field.

Definitions:
  - count   = every element of the category and type in the snapshot.
  - Length, Area and Volume are read from ``params`` of each element and converted to
    m, m2 and m3 from ``snapshot_units`` (feet by default, like geometry_screening).
  - A quantity is summed over the elements that carry a number for it. When no element
    does, the total is empty (None), never 0. ``*_elements`` says how many contributed.
  - An element with none of the three quantities is listed as "without quantity" and still
    counted in ``count``.
  - BC3 measurement per type: ``bc3_measure`` or, with auto, area for walls, floors, roofs,
    ceilings and rooms, length for linear MEP and framing, volume for columns and
    foundations, and count (unit ud) for everything else. A type without the chosen
    quantity falls back to count.
"""
from __future__ import annotations
from revit_mcp_server.security.module_permissions import writable_path

import csv
import importlib.util
import io
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_MAX_ROWS = 500
FEET_TO_METRES = 0.3048
UNITS = {"feet": FEET_TO_METRES, "ft": FEET_TO_METRES, "metres": 1.0, "meters": 1.0, "m": 1.0}
MEASURES = ("length", "area", "volume")
OUT_NAME = {"length": "length_m", "area": "area_m2", "volume": "volume_m3"}
POWER = {"length": 1, "area": 2, "volume": 3}
PARAM = {"length": "Length", "area": "Area", "volume": "Volume"}
BC3_UNIT = {"count": "ud", "length": "m", "area": "m2", "volume": "m3"}
BC3_MEASURES = ("auto", "count") + MEASURES
AUTO_MEASURE = {
    **dict.fromkeys(("walls", "floors", "roofs", "ceilings", "rooms"), "area"),
    **dict.fromkeys(("pipecurves", "ductcurves", "flexpipecurves", "flexductcurves", "cabletray",
                     "conduit", "structuralframing", "railings"), "length"),
    **dict.fromkeys(("structuralcolumns", "structuralfoundation", "columns"), "volume"),
}
NO_TYPE = "(no type)"


def _sibling(module_id: str) -> Any:
    """Load another module's module.py by file path (the server loads modules as plain modules)."""
    path = Path(__file__).resolve().parent.parent / module_id / "module.py"
    spec = importlib.util.spec_from_file_location(f"_qto_export_{module_id}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rg = _sibling("report_generator")


def _number(el: Dict[str, Any], name: str) -> Optional[float]:
    info = (el.get("params") or {}).get(name)
    value = info.get("v") if isinstance(info, dict) else info
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and abs(out) != float("inf") else None


def _type_label(el: Dict[str, Any]) -> str:
    family, name = str(el.get("family") or "").strip(), str(el.get("type_name") or "").strip()
    return f"{family}: {name}" if family and name else (family or name or NO_TYPE)


def compute_quantities(
    elements: List[Dict[str, Any]], to_m: float = 1.0, categories: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Rows per (category, type) and the elements without any quantity. Pure function."""
    wanted = set(categories or [])
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    without: List[Dict[str, Any]] = []
    for el in elements:
        if not isinstance(el, dict):
            continue
        cat = el.get("category") or "(none)"
        if wanted and cat not in wanted:
            continue
        label = _type_label(el)
        g = groups.setdefault((cat, label), {"count": 0, "no_quantity": 0,
                                             **{m: [0.0, 0] for m in MEASURES}})
        g["count"] += 1
        found = False
        for m in MEASURES:
            v = _number(el, PARAM[m])
            if v is not None:
                g[m][0] += v * to_m ** POWER[m]
                g[m][1] += 1
                found = True
        if not found:
            g["no_quantity"] += 1
            without.append({"uid": el.get("uid"), "element_id": el.get("element_id"),
                            "category": cat, "type": label, "level_uid": el.get("level_uid")})
    rows = []
    for (cat, label) in sorted(groups):
        g = groups[(cat, label)]
        row: Dict[str, Any] = {"category": cat, "type": label, "count": g["count"]}
        for m in MEASURES:
            row[OUT_NAME[m]] = round(g[m][0], 4) if g[m][1] else None
            row[m + "_elements"] = g[m][1]
        row["no_quantity"] = g["no_quantity"]
        rows.append(row)
    return {"rows": rows, "without_quantity": without,
            "element_count": sum(g["count"] for g in groups.values())}


def _num_text(value: Any) -> Any:
    if isinstance(value, float):
        return ("%.4f" % value).rstrip("0").rstrip(".")
    return "" if value is None else value


def _safe(value: Any) -> Any:
    # A leading = + - @ would be run as a formula by a spreadsheet; names come from the model.
    return "'" + value if isinstance(value, str) and value[:1] in ("=", "+", "-", "@") else value


def _cell(value: Any) -> Any:
    return _safe(value) if isinstance(value, str) else _num_text(value)


def _csv_text(rows: List[Dict[str, Any]]) -> str:
    cols = ["category", "type", "count", "length_m", "area_m2", "volume_m3", "no_quantity"]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(cols)
    for r in rows:
        writer.writerow([_cell(r[c]) for c in cols])
    return out.getvalue()


def _missing_csv_text(items: List[Dict[str, Any]]) -> str:
    cols = ["uid", "element_id", "category", "type", "level_uid"]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(cols)
    for it in items:
        writer.writerow([_cell(it.get(c)) for c in cols])
    return out.getvalue()


def _clean(text: Any, limit: int = 120) -> str:
    """BC3 fields cannot hold | ~ \\ or line breaks."""
    return re.sub(r"\s+", " ", re.sub(r"[|~\\\r\n]", " ", str(text))).strip()[:limit]


def _pick_measure(row: Dict[str, Any], category: str, requested: str) -> str:
    cat = category[4:] if category.lower().startswith("ost_") else category
    want = AUTO_MEASURE.get(cat.lower(), "count") if requested == "auto" else requested
    return want if want != "count" and row[OUT_NAME[want]] is not None else "count"


def _bc3_text(rows: List[Dict[str, Any]], snapshot_id: str, measure: str) -> str:
    lines = [
        "~V|AEC Model Bridge|FIEBDC-3/2016|AEC Model Bridge|"
        + _clean(f"QTO {snapshot_id}") + "|ANSI|"
        + _clean(f"Quantity take-off from snapshot {snapshot_id}") + "|",
    ]
    chapters: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        chapters[r["category"]].append(r)
    root = "QTO##"
    lines.append(f"~C|{root}||{_clean('Quantity take-off')}||||")
    chapter_codes = {cat: f"C{i:02d}#" for i, cat in enumerate(chapters, 1)}
    lines.append(f"~D|{root}|" + "".join(f"{c}\\1\\1\\" for c in chapter_codes.values()) + "|")
    for cat, code in chapter_codes.items():
        lines.append(f"~C|{code}||{_clean(cat)}||||")
        items = []
        for j, r in enumerate(chapters[cat], 1):
            item = f"{code[:-1]}.{j:03d}"
            m = _pick_measure(r, cat, measure)
            qty = float(r["count"]) if m == "count" else r[OUT_NAME[m]]
            text = _num_text(float(qty))
            lines.append(f"~C|{item}|{BC3_UNIT[m]}|{_clean(r['type'])}||||")
            used = r["count"] if m == "count" else r[m + "_elements"]
            comment = _clean(f"{used} of {r['count']} elements")
            body = f"\\{comment}\\{text}\\\\\\\\" if m == "count" else f"\\{comment}\\1\\{text}\\\\\\"
            lines.append(f"~M|{code}\\{item}|{j}|{text}|{body}|")
            items.append(f"{item}\\1\\{text}\\")
        lines.append(f"~D|{code}|" + "".join(items) + "|")
    return "\r\n".join(lines) + "\r\n"


def _ansi(text: str) -> Tuple[bytes, int, List[str]]:
    """cp1252 bytes, the number of characters replaced by '?', and the names they were in."""
    count, names = 0, []
    for line in text.split(chr(13) + chr(10)):
        bad = sum(1 for ch in line if ch != "?" and ch.encode("cp1252", errors="replace") == b"?")
        if bad:
            count += bad
            fields = line.split("|")
            names.append(fields[3] if line.startswith("~C") and len(fields) > 3 else line[:2])
    return text.encode("cp1252", errors="replace"), count, names


def _check_name(filename: str, suffix: str) -> None:
    if not isinstance(filename, str) or not filename.lower().endswith(suffix):
        raise ValueError(f"The output file name must end in {suffix}")


def _write(workspace: Any, filename: str, data: bytes) -> str:
    path = writable_path(workspace, rg._confined(workspace, filename))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


class QtoExportModule:
    def run(
        self,
        snapshot_id: str = "",
        categories: Optional[List[str]] = None,
        snapshot_units: str = "feet",
        bc3_measure: str = "auto",
        max_rows: int = DEFAULT_MAX_ROWS,
        csv_filename: str = "",
        bc3_filename: str = "",
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        if snapshot_units not in UNITS:
            raise ValueError("snapshot_units must be 'feet' or 'metres'.")
        if bc3_measure not in BC3_MEASURES:
            raise ValueError("bc3_measure must be one of: " + ", ".join(BC3_MEASURES))
        max_rows = max(1, int(max_rows or DEFAULT_MAX_ROWS))
        if csv_filename:
            _check_name(csv_filename, ".csv")
        if bc3_filename:
            _check_name(bc3_filename, ".bc3")
        data = rg._load_review_snapshot(snapshot_id, workspace)  # refuses mock data in bridge mode
        if not isinstance(data["elements"], list):
            raise ValueError("The snapshot has no 'elements' list.")
        result = compute_quantities(data["elements"], UNITS[snapshot_units], categories)
        rows, without = result["rows"], result["without_quantity"]
        partial = rg._is_partial_snapshot(data)
        notes = [
            f"Length, Area and Volume are read from element parameters and converted from {snapshot_units} to m, m2 and m3.",
            "An empty total means no element of that type carries the quantity. It is not zero.",
        ]
        if partial:
            notes.append("The snapshot is a partial capture: quantities describe the captured elements only.")
        if data["is_mock"]:
            notes.append("MOCK data: generated sample, not a live Revit model.")
        if not data["elements"]:
            notes.append("The snapshot has no elements.")
        if without:
            notes.append(f"{len(without)} elements have no Length, Area or Volume; they are counted and listed in without_quantity.")
        files: Dict[str, str] = {}
        if csv_filename:
            files["csv_file"] = _write(workspace, csv_filename, _csv_text(rows).encode("utf-8"))
            missing_name = csv_filename[:-4] + "_no_quantity.csv"
            files["no_quantity_file"] = _write(workspace, missing_name, _missing_csv_text(without).encode("utf-8"))
        if bc3_filename:
            text = _bc3_text(rows, data["snapshot_id"], bc3_measure)
            raw, replaced, names = _ansi(text)
            files["bc3_file"] = _write(workspace, bc3_filename, raw)
            if replaced:
                notes.append(
                    f"{replaced} characters cannot be written in the BC3 ANSI (cp1252) character set and became '?' "
                    f"in {len(names)} records: " + "; ".join(dict.fromkeys(names)) + ".")
        return {
            "read_only": True,
            "mock": data["is_mock"],
            "data_source": "MOCK DATA - generated sample, not your model." if data["is_mock"] else "Saved snapshot",
            "snapshot_id": data["snapshot_id"],
            "partial": partial,
            "snapshot_units": snapshot_units,
            "element_count": result["element_count"],
            "row_total": len(rows),
            "rows_shown": min(len(rows), max_rows),
            "rows": rows[:max_rows],
            "without_quantity_total": len(without),
            "without_quantity": without[:max_rows],
            "notes": notes,
            **files,
        }
