"""
model_health module - a model health score per snapshot, and its trend over time.

Command:
  score - Health score (0 to 100, higher is better) of one saved snapshot with its components,
          and the same score for every saved snapshot of the same document (doc_guid), oldest
          first, with the change from the previous point. Optional CSV in the workspace, and an
          optional self-contained HTML dashboard (``html_filename``): score and components, the
          trend, top open issues from the latest stored QA/QC run of the document (the issue
          store is opened read-only, never written), and parameter completeness.

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
import html
import importlib.util
import io
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

WEIGHTS = {"warnings": 25, "qa_findings": 25, "unplaced_rooms": 20, "unused_types": 15, "completeness": 15}
WARNINGS_PENALTY_PER_1000 = 5
COMPLETENESS_TOP_N = 5
DEFAULT_MAX_POINTS = 50
MAX_POINTS = 500
DASHBOARD_TOP_ISSUES = 10
DASHBOARD_MAX_COMPLETENESS_ROWS = 400
QA_DB_FILENAME = "qaqc_issues.db"  # qaqc_checker's issue store; only ever opened read-only here
_SEV_RANK = {"error": 0, "warning": 1, "info": 2}


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
                                     rule_pack, workspace, failed, data.get("relations"))
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


def latest_qa_issues(workspace: Any, doc_guid: str, top: int = DASHBOARD_TOP_ISSUES) -> Dict[str, Any]:
    """Open issues of the latest stored QA/QC run for this document, grouped per rule.

    Reads qaqc_checker's SQLite store in read-only mode. A missing store, a document with no run
    and an unreadable store are reported with a status, never as "no issues"."""
    if not doc_guid:
        return {"status": "no_doc_guid", "groups": [],
                "note": "The snapshot has no document id (source.doc_guid), so its QA/QC runs cannot be found."}
    path = Path(workspace.allowed_directories[0]) / QA_DB_FILENAME
    if not path.is_file():
        return {"status": "no_run", "groups": [],
                "note": "No QA/QC run is stored in this workspace. Run qaqc_checker_run_check to list issues here."}
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            conn.row_factory = sqlite3.Row
            run = conn.execute(
                "SELECT rule_pack, snapshot_id, run_at FROM qaqc_runs WHERE doc_guid=? ORDER BY id DESC LIMIT 1",
                (doc_guid,),
            ).fetchone()
            if run is None:
                return {"status": "no_run", "groups": [],
                        "note": "No QA/QC run is stored for this document. Run qaqc_checker_run_check to list issues here."}
            rows = conn.execute(
                "SELECT rule_id, severity, message, label FROM issues "
                "WHERE doc_guid=? AND rule_pack=? AND status='open' AND last_seen_at=?",
                (doc_guid, run["rule_pack"], run["run_at"]),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {"status": "unreadable", "groups": [],
                "note": f"The QA/QC issue store could not be read ({exc}), so issues are unknown."}
    groups: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        g = groups.setdefault(r["rule_id"], {"rule_id": r["rule_id"], "severity": r["severity"],
                                             "message": r["message"], "count": 0, "examples": []})
        g["count"] += 1
        if r["label"] and len(g["examples"]) < 3 and r["label"] not in g["examples"]:
            g["examples"].append(r["label"])
    ordered = sorted(groups.values(), key=lambda g: (_SEV_RANK.get(g["severity"], 9), -g["count"], g["rule_id"]))
    return {
        "status": "ok", "rule_pack": run["rule_pack"], "snapshot_id": run["snapshot_id"] or "unknown",
        "run_at": run["run_at"], "open_issues": len(rows), "rules_hit": len(ordered), "groups": ordered[:top],
    }


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _hue(score: Optional[float]) -> str:
    if score is None:
        return "#d1d5db"
    return f"hsl({round(120 * max(0.0, min(100.0, score)) / 100)}, 60%, 72%)"


def _trend_svg(points: List[Dict[str, Any]]) -> str:
    scored = [p for p in points if p.get("score") is not None]
    if len(scored) < 2:
        return ""
    w, h, pad = 640, 200, 30
    step = (w - 2 * pad) / (len(scored) - 1)
    xy = [(pad + i * step, h - pad - (h - 2 * pad) * p["score"] / 100) for i, p in enumerate(scored)]
    parts = [f'<svg class="trend" viewBox="0 0 {w} {h}" role="img" aria-label="Health score per snapshot, oldest first">']
    for v in (0, 50, 100):
        y = h - pad - (h - 2 * pad) * v / 100
        parts.append(f'<line x1="{pad}" x2="{w - pad}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                     f'<text x="4" y="{y + 4:.1f}" class="axis">{v}</text>')
    parts.append('<polyline fill="none" class="line" points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in xy) + '"/>')
    for (x, y), p in zip(xy, scored):
        mark = "dot" if not p.get("partial") else "dot partial"
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" class="{mark}"><title>{_esc(p["snapshot_id"])}: '
                     f'{_esc(p["score"])}{" (partial)" if p.get("partial") else ""}</title></circle>')
    parts.append("</svg>")
    return "".join(parts)


def _inputs_text(inputs: Dict[str, Any]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in inputs.items())


def dashboard_html(result: Dict[str, Any], doc_title: str, qa: Dict[str, Any],
                   completeness_rows: List[Dict[str, Any]]) -> str:
    """One self-contained page (inline CSS and SVG, no scripts, fonts or links). All text is escaped."""
    title = "Model health: " + (doc_title or result["snapshot_id"])
    score = result["score"]
    out = [
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        f"<title>{_esc(title)}</title><style>"
        ":root{--fg:#111;--bg:#fff;--muted:#555;--line:#c7c7c7;--accent:#2457a6}"
        "@media (prefers-color-scheme: dark){:root{--fg:#e8e8e8;--bg:#16181b;--muted:#a8a8a8;--line:#444;--accent:#7aa7e8}}"
        "body{font:14px system-ui,sans-serif;margin:16px;max-width:980px;color:var(--fg);background:var(--bg)}"
        "h1{font-size:22px}h2{font-size:17px;margin-top:28px}"
        "table{border-collapse:collapse;margin:8px 0;width:100%}th,td{border:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}"
        "td.n{text-align:right;white-space:nowrap}.muted{color:var(--muted)}"
        ".score{display:inline-block;font-size:40px;font-weight:700;padding:8px 18px;border-radius:8px;color:#111}"
        ".warn{background:#fff3cd;color:#111;border:1px solid #d6b656;padding:8px;margin:8px 0}"
        ".sev-error{font-weight:700;color:#b42318}.sev-warning{color:#9a6700}"
        ".trend{width:100%;max-width:640px;height:auto}.trend .grid{stroke:var(--line)}"
        ".trend .axis{font-size:11px;fill:var(--muted)}.trend .line{stroke:var(--accent);stroke-width:2}"
        ".trend .dot{fill:var(--accent)}.trend .dot.partial{fill:var(--bg);stroke:var(--accent);stroke-width:2}"
        ".table-wrap{overflow-x:auto}"
        "</style></head><body>",
        f"<h1>{_esc(title)}</h1>",
        f"<p class=\"muted\">Snapshot {_esc(result['snapshot_id'])} taken {_esc(result['taken_at'] or 'at an unknown time')}. "
        "Read-only report built from saved data; nothing in the model was changed.</p>",
    ]
    if result.get("mock"):
        out.append("<p class=\"warn\"><strong>Mock data.</strong> Generated sample, not a live Revit model.</p>")
    if result.get("partial"):
        out.append("<p class=\"warn\"><strong>Partial capture.</strong> The score describes the captured elements only.</p>")

    out.append("<h2>Health score</h2>")
    out.append(f"<p><span class=\"score\" style=\"background:{_hue(score)}\">{_esc('n/a' if score is None else score)}</span>"
               " <span class=\"muted\">out of 100, higher is better</span></p>")
    if result["components"]:
        out.append("<div class=\"table-wrap\"><table><tr><th>Component</th><th>Weight</th><th>Subscore</th><th>Inputs</th></tr>")
        for c in result["components"]:
            out.append(f"<tr><td>{_esc(c['name'])}</td><td class=\"n\">{_esc(c['weight'])}</td>"
                       f"<td class=\"n\" style=\"background:{_hue(c['subscore'])};color:#111\">{_esc(c['subscore'])}</td>"
                       f"<td>{_esc(_inputs_text(c['inputs']))}</td></tr>")
        out.append("</table></div>")
    else:
        out.append("<p>No component could be scored from this snapshot.</p>")
    if result["excluded"]:
        out.append("<p>Left out of the score (not counted as 0):</p><ul>"
                   + "".join(f"<li><strong>{_esc(e['name'])}</strong>: {_esc(e['reason'])}</li>" for e in result["excluded"])
                   + "</ul>")

    out.append("<h2>Trend across saved snapshots</h2>")
    trend = result["trend"]
    points = trend.get("points") or []
    if not trend.get("included"):
        out.append("<p>Trend not requested (include_trend was false).</p>")
    elif not points:
        out.append(f"<p>{_esc(trend.get('note') or 'No saved snapshots of this document.')}</p>")
    else:
        svg = _trend_svg(points)
        out.append(svg or "<p>Fewer than two scored snapshots, so there is no line to draw.</p>")
        out.append("<div class=\"table-wrap\"><table><tr><th>Snapshot</th><th>Taken</th><th>Score</th><th>Change</th><th>Note</th></tr>")
        for p in points:
            note = p.get("delta_note") or ""
            if p.get("partial"):
                note = ("Partial capture. " + note).strip()
            if p.get("time_estimated"):
                note = (note + " Time from file date.").strip()
            delta = "" if p["delta"] is None else f"{p['delta']:+.1f}"
            out.append(f"<tr><td>{_esc(p['snapshot_id'])}</td><td>{_esc(p['taken_at'])}</td>"
                       f"<td class=\"n\">{_esc('n/a' if p['score'] is None else p['score'])}</td>"
                       f"<td class=\"n\">{_esc(delta)}</td><td>{_esc(note)}</td></tr>")
        out.append("</table></div>")

    out.append("<h2>Top issues from the latest QA/QC run</h2>")
    if qa["status"] != "ok":
        out.append(f"<p>{_esc(qa['note'])}</p>")
    else:
        out.append(f"<p class=\"muted\">Rule pack {_esc(qa['rule_pack'])}, run {_esc(qa['run_at'])} on snapshot "
                   f"{_esc(qa['snapshot_id'])}: {qa['open_issues']} open issue(s) over {qa['rules_hit']} rule(s).</p>")
        if qa["snapshot_id"] != result["snapshot_id"]:
            out.append("<p class=\"warn\">This QA/QC run was on a different snapshot than the score above.</p>")
        if not qa["groups"]:
            out.append("<p>The latest run recorded no open issues.</p>")
        else:
            out.append("<div class=\"table-wrap\"><table><tr><th>Severity</th><th>Rule</th><th>Issues</th><th>Description</th><th>Examples</th></tr>")
            for g in qa["groups"]:
                sev = g["severity"] if g["severity"] in _SEV_RANK else "info"
                out.append(f"<tr><td class=\"sev-{sev}\">{_esc(g['severity'])}</td><td>{_esc(g['rule_id'])}</td>"
                           f"<td class=\"n\">{g['count']}</td><td>{_esc(g['message'])}</td>"
                           f"<td>{_esc(', '.join(g['examples']))}</td></tr>")
            out.append("</table></div>")
            if qa["rules_hit"] > len(qa["groups"]):
                out.append(f"<p class=\"muted\">Showing the top {len(qa['groups'])} of {qa['rules_hit']} rules.</p>")

    out.append(f"<h2>Parameter completeness</h2><p class=\"muted\">Fill rate of the {COMPLETENESS_TOP_N} most common "
               "parameters per category. An element without the parameter counts as not filled.</p>")
    if not completeness_rows:
        out.append("<p>No element carries any parameter.</p>")
    else:
        shown = completeness_rows[:DASHBOARD_MAX_COMPLETENESS_ROWS]
        out.append("<div class=\"table-wrap\"><table><tr><th>Category</th><th>Parameter</th><th>Filled</th><th>Percent</th></tr>")
        for r in shown:
            pct = "n/a" if r["percent"] is None else f"{r['percent']:.1f}%"
            out.append(f"<tr><td>{_esc(r['category'])}</td><td>{_esc(r['parameter'])}</td>"
                       f"<td class=\"n\">{r['filled']}/{r['total']}</td>"
                       f"<td class=\"n\" style=\"background:{_hue(r['percent'])};color:#111\">{_esc(pct)}</td></tr>")
        out.append("</table></div>")
        if len(completeness_rows) > len(shown):
            out.append(f"<p class=\"muted\">Showing {len(shown)} of {len(completeness_rows)} rows; "
                       "param_completeness_heatmap gives every row.</p>")

    if result["notes"]:
        out.append("<h2>Notes</h2><ul>" + "".join(f"<li>{_esc(n)}</li>" for n in result["notes"]) + "</ul>")
    out.append("</body></html>")
    return "".join(out)


class ModelHealthModule:
    def score(
        self,
        snapshot_id: str = "",
        rule_pack: str = "",
        include_trend: bool = True,
        max_points: int = DEFAULT_MAX_POINTS,
        csv_filename: str = "",
        html_filename: str = "",
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        max_points = max(1, min(int(max_points or DEFAULT_MAX_POINTS), MAX_POINTS))
        if html_filename and not (isinstance(html_filename, str) and html_filename.lower().endswith(".html")):
            raise ValueError("html_filename must end in .html")
        data =rg._load_review_snapshot(snapshot_id, workspace)  # refuses mock data in bridge mode
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
        result = {
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
        }
        if html_filename:
            qa = latest_qa_issues(workspace, doc_guid)
            cells = pc.compute_cells(data["elements"], None, COMPLETENESS_TOP_N)["rows"]
            page = dashboard_html(result, str(data["source"].get("doc_title") or ""), qa, cells)
            path = writable_path(workspace, rg._confined(workspace, html_filename))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(page, encoding="utf-8")
            files["html_file"] = str(path)
            result["dashboard"] = {"qa_status": qa["status"], "qa_note": qa.get("note", ""),
                                   "qa_issue_groups": len(qa["groups"]), "completeness_rows": len(cells)}
        result.update(files)
        return result
