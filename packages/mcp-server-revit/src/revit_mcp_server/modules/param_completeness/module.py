"""
param_completeness module - parameter fill rate per category and parameter (optionally per level).

Command:
  heatmap - For a saved snapshot, count how many elements of each category have a value in
            each parameter: filled / total / percent. Optional CSV and a self-contained
            HTML heatmap are written inside the workspace.

Read-only: nothing in the model is changed. The files are written to the workspace only.

Definitions (also in docs/qa-handover-report.md):
  - total   = elements of that category in the snapshot (and on that level, with by_level).
  - filled  = elements whose parameter has a value that is not null and not blank text.
              "0" and "false" are values. An element that does not carry the parameter at all
              counts as not filled, so the percentage is "of all elements of the category".
  - Parameters are chosen by the caller, or the ``top_n`` most common per category (carried
    by the most elements; ties by name).
"""
from __future__ import annotations

import csv
import html
import importlib.util
import io
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_TOP_N = 8
MAX_TOP_N = 50
MAX_PARAMETERS = 100
DEFAULT_MAX_ROWS = 500
NO_LEVEL = "(no level)"


def _sibling(module_id: str) -> Any:
    """Load another module's module.py by file path (the server loads modules as plain modules)."""
    path = Path(__file__).resolve().parent.parent / module_id / "module.py"
    spec = importlib.util.spec_from_file_location(f"_param_completeness_{module_id}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rg = _sibling("report_generator")


def is_filled(value: Any) -> bool:
    """A value counts when it is not null and not blank text."""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _param_value(el: Dict[str, Any], name: str) -> Tuple[bool, Any]:
    params = el.get("params") or {}
    if name not in params:
        return False, None
    info = params[name]
    return True, (info.get("v") if isinstance(info, dict) else info)


def _level_labels(elements: List[Dict[str, Any]]) -> Dict[str, str]:
    labels: Dict[str, str] = {}
    for el in elements:
        if el.get("category") == "OST_Levels" and el.get("uid"):
            labels[el["uid"]] = str(el.get("name") or el.get("type_name") or el["uid"])
    return labels


def compute_cells(
    elements: List[Dict[str, Any]],
    parameters: Optional[List[str]] = None,
    top_n: int = DEFAULT_TOP_N,
    categories: Optional[List[str]] = None,
    by_level: bool = False,
) -> Dict[str, Any]:
    """Fill rates per (category, parameter[, level]). Pure function over element records."""
    wanted = set(categories or [])
    by_cat: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for el in elements:
        cat = el.get("category") or "(none)"
        if wanted and cat not in wanted:
            continue
        by_cat[cat].append(el)
    labels = _level_labels(elements) if by_level else {}
    chosen = list(dict.fromkeys(parameters or []))
    rows: List[Dict[str, Any]] = []
    for cat in sorted(by_cat):
        els = by_cat[cat]
        if chosen:
            names = chosen
        else:
            carried: Dict[str, int] = defaultdict(int)
            for el in els:
                for name in (el.get("params") or {}):
                    carried[name] += 1
            names = [n for n, _ in sorted(carried.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]]
        groups: Dict[Optional[str], List[Dict[str, Any]]] = {None: els}
        if by_level:
            groups = defaultdict(list)
            for el in els:
                uid = el.get("level_uid")
                groups[labels.get(uid, uid) if uid else NO_LEVEL].append(el)
        for name in names:
            for level in sorted(groups, key=lambda g: (g is None, str(g))):
                group = groups[level]
                filled = sum(1 for el in group if is_filled(_param_value(el, name)[1]))
                row = {
                    "category": cat, "parameter": name,
                    "filled": filled, "total": len(group),
                    "percent": round(100.0 * filled / len(group), 1) if group else None,
                }
                if by_level:
                    row["level"] = level
                rows.append(row)
    missing = [p for p in chosen if not any(r["parameter"] == p and r["filled"] for r in rows)]
    return {"rows": rows, "element_count": sum(len(v) for v in by_cat.values()),
            "categories": sorted(by_cat), "parameters_never_filled": missing}


def _csv_text(rows: List[Dict[str, Any]], by_level: bool) -> str:
    out = io.StringIO()
    cols = ["category", "parameter"] + (["level"] if by_level else []) + ["filled", "total", "percent"]
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(cols)
    for r in rows:
        # A leading = + - @ would be run as a formula by a spreadsheet; names come from the model.
        writer.writerow([("'" + str(r[c]) if isinstance(r[c], str) and r[c][:1] in "=+-@" else r[c]) for c in cols])
    return out.getvalue()


def _colour(percent: Optional[float]) -> str:
    if percent is None:
        return "#e5e7eb"
    hue = round(120 * percent / 100)  # red (0) to green (120)
    return f"hsl({hue}, 60%, 78%)"


def _html_text(title: str, coverage: List[Dict[str, str]], rows: List[Dict[str, Any]], by_level: bool, partial: bool) -> str:
    esc = html.escape
    parts = [
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        f"<title>{esc(title)}</title>",
        "<style>body{font:14px system-ui,sans-serif;margin:16px;color:#111;background:#fff}"
        "table{border-collapse:collapse;margin:8px 0 24px}th,td{border:1px solid #bbb;padding:4px 8px;text-align:right}"
        "th:first-child,td:first-child{text-align:left}td small{color:#444}"
        ".warn{background:#fff3cd;border:1px solid #d6b656;padding:8px;margin:8px 0}"
        "dl{display:grid;grid-template-columns:max-content 1fr;gap:2px 12px}dt{font-weight:600}dd{margin:0}</style>",
        "</head><body>",
        f"<h1>{esc(title)}</h1>",
    ]
    if partial:
        parts.append("<p class=\"warn\"><strong>Partial capture.</strong> These fill rates cover part of the model, not the whole model.</p>")
    parts.append("<dl>" + "".join(f"<dt>{esc(c['item'])}</dt><dd>{esc(c['detail'])}</dd>" for c in coverage) + "</dl>")
    by_cat: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    for cat, crows in by_cat.items():
        cols = list(dict.fromkeys(r.get("level", "All elements") for r in crows))
        params = list(dict.fromkeys(r["parameter"] for r in crows))
        cell = {(r["parameter"], r.get("level", "All elements")): r for r in crows}
        parts.append(f"<h2>{esc(cat)}</h2><table><tr><th>Parameter</th>" + "".join(f"<th>{esc(str(c))}</th>" for c in cols) + "</tr>")
        for p in params:
            parts.append(f"<tr><td>{esc(p)}</td>")
            for c in cols:
                r = cell.get((p, c))
                if r is None:
                    parts.append("<td></td>")
                else:
                    pct = "n/a" if r["percent"] is None else f"{r['percent']:.1f}%"
                    parts.append(f"<td style=\"background:{_colour(r['percent'])}\">{pct}<br><small>{r['filled']}/{r['total']}</small></td>")
            parts.append("</tr>")
        parts.append("</table>")
    parts.append("</body></html>")
    return "".join(parts)


def _write(workspace: Any, filename: str, suffix: str, text: str) -> str:
    if not isinstance(filename, str) or not filename.lower().endswith(suffix):
        raise ValueError(f"The output file name must end in {suffix}")
    path = rg._confined(workspace, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


class ParamCompletenessModule:
    def heatmap(
        self,
        snapshot_id: str = "",
        parameters: Optional[List[str]] = None,
        top_n: int = DEFAULT_TOP_N,
        categories: Optional[List[str]] = None,
        by_level: bool = False,
        max_rows: int = DEFAULT_MAX_ROWS,
        csv_filename: str = "",
        html_filename: str = "",
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        parameters = [str(p) for p in (parameters or []) if str(p).strip()]
        if len(parameters) > MAX_PARAMETERS:
            raise ValueError(f"At most {MAX_PARAMETERS} parameters can be listed.")
        top_n = max(1, min(int(top_n or DEFAULT_TOP_N), MAX_TOP_N))
        max_rows = max(1, int(max_rows or DEFAULT_MAX_ROWS))
        data = rg._load_review_snapshot(snapshot_id, workspace)  # refuses mock data in bridge mode
        result = compute_cells(data["elements"], parameters, top_n, categories, bool(by_level))
        rows = result["rows"]
        partial = rg._is_partial_snapshot(data)
        coverage = [
            {"item": a, "detail": str(b).replace("the findings in this workbook cover", "these fill rates cover")}
            for a, b in rg._coverage_rows(data, [])
        ]
        if categories:
            coverage.append({"item": "Category selection", "detail": "Only these categories are shown: " + ", ".join(categories)})
        notes = [
            "total = elements of the category in the snapshot; an element without the parameter counts as not filled.",
        ]
        if partial:
            notes.append("The snapshot is a partial capture: fill rates describe the captured elements only.")
        if data["is_mock"]:
            notes.append("MOCK data: generated sample, not a live Revit model.")
        if not data["elements"]:
            notes.append("The snapshot has no elements.")
        if result["parameters_never_filled"]:
            notes.append("Not filled on any element in the selected categories: " + ", ".join(result["parameters_never_filled"]))
        files: Dict[str, str] = {}
        if csv_filename:
            files["csv_file"] = _write(workspace, csv_filename, ".csv", _csv_text(rows, bool(by_level)))
        if html_filename:
            title = "Parameter completeness: " + str(data["source"].get("doc_title") or data["snapshot_id"])
            files["html_file"] = _write(workspace, html_filename, ".html", _html_text(title, coverage, rows, bool(by_level), partial))
        return {
            "read_only": True,
            "mock": data["is_mock"],
            "data_source": "MOCK DATA - generated sample, not your model." if data["is_mock"] else "Saved snapshot",
            "snapshot_id": data["snapshot_id"],
            "partial": partial,
            "coverage": coverage,
            "by_level": bool(by_level),
            "element_count": result["element_count"],
            "categories": result["categories"],
            "row_total": len(rows),
            "rows_shown": min(len(rows), max_rows),
            "rows": rows[:max_rows],
            "notes": notes,
            **files,
        }
