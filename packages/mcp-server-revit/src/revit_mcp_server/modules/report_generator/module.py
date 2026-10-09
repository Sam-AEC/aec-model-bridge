"""
report_generator module — P14 Excel / SQLite reporting (W8, W16).

Commands:
  export_excel         — Generate a multi-sheet .xlsx: Elements, Params, QA Findings.
  export_sqlite_summary — Write elements + types into a fresh SQLite db.
  build_review_pack    — One 'Model review' .xlsx for a coordinator: Cover, Findings,
                         Counts by category, What to do next.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)

_HEADER_FONT = Font(bold=True, color="FFFFFF")
_HEADER_FILL = PatternFill("solid", fgColor="2C5F8A")

SEVERITY_COLORS = {
    "error": "FFE0E0",
    "warning": "FFF3CD",
    "info": "E0F0FF",
}


def _ws_dir(workspace: Any) -> Path:
    return workspace.allowed_directories[0]

def _get_data(snapshot_id: str, workspace: Any):
    if not snapshot_id:
        from revit_mcp_server.semantic.engine import generate_mock_snapshot, require_snapshot_or_mock
        require_snapshot_or_mock(snapshot_id, "report_generator")
        snap = generate_mock_snapshot()
        return (
            [el.model_dump(by_alias=True) for el in snap.elements],
            [t.model_dump() for t in snap.types],
        )
    path = _ws_dir(workspace) / "snapshots" / f"{snapshot_id}.json"
    if not path.exists():
        raise ValueError(f"Snapshot '{snapshot_id}' not found.")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("elements", []), data.get("types", [])

def _match_element(el: Dict[str, Any], filter_dsl: Dict[str, Any]) -> bool:
    if not filter_dsl:
        return True
    for key, val in filter_dsl.items():
        if key == "category":
            cats = val if isinstance(val, list) else [val]
            if el.get("category") not in cats:
                return False
        elif key == "family" and el.get("family") != val:
            return False
        elif key == "type_name" and el.get("type_name") != val:
            return False
    return True

def _load_source(snapshot_id: str, workspace: Any) -> Dict[str, Any]:
    """Document identity of the snapshot, so a report says what it describes."""
    if not snapshot_id:
        return {"doc_title": "Generated mock data (not a live model)", "doc_guid": "mock-doc"}
    path = _ws_dir(workspace) / "snapshots" / f"{snapshot_id}.json"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data.get("source", {}) or {}


def _write_summary_sheet(ws: Any, snapshot_id: str, source: Dict[str, Any], element_count: int, issues: List[Dict[str, Any]]) -> None:
    from datetime import datetime, timezone

    rows = [
        ("Snapshot ID", snapshot_id or "(mock)"),
        ("Document", source.get("doc_title") or source.get("title") or ""),
        ("Document GUID", source.get("doc_guid", "")),
        ("Report generated (UTC)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
        ("Elements in report", element_count),
        ("QA/QC issues", len(issues)),
    ]
    for label, count in sorted(_count_by(issues, "severity").items()):
        rows.append((f"  {label or 'unspecified'} severity", count))
    for label, count in sorted(_count_by(issues, "status").items()):
        rows.append((f"  status: {label or 'unspecified'}", count))
    _write_header(ws, ["Item", "Value"])
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 48
    for row in rows:
        ws.append(list(row))


def _count_by(issues: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for issue in issues:
        value = str(issue.get(key, "") or "")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _write_header(ws: Any, headers: List[str]) -> None:
    for col, title in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=title)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[get_column_letter(col)].width = max(12, len(title) + 2)

def _load_qaqc_issues(workspace: Any) -> List[Dict[str, Any]]:
    db_path = _ws_dir(workspace) / "qaqc_issues.db"
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM issues").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Model review pack (one-file coordinator workbook)
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
_SEVERITY_LABEL = {"error": "Must fix", "warning": "Should fix", "info": "For information"}


def _load_review_snapshot(snapshot_id: str, workspace: Any) -> Dict[str, Any]:
    """Elements, types, identity and time for a snapshot (or generated mock data)."""
    if not snapshot_id:
        from revit_mcp_server.semantic.engine import generate_mock_snapshot, require_snapshot_or_mock
        require_snapshot_or_mock(snapshot_id, "report_generator")
        snap = generate_mock_snapshot()
        return {
            "snapshot_id": snap.snapshot_id,
            "taken_at": snap.taken_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "source": {"doc_title": "Generated mock data (not a live model)", "doc_guid": "mock-doc"},
            "elements": [el.model_dump(by_alias=True) for el in snap.elements],
            "types": [t.model_dump() for t in snap.types],
            "is_mock": True,
        }
    snap_dir = (_ws_dir(workspace) / "snapshots").resolve()
    path = (snap_dir / f"{snapshot_id}.json").resolve()
    if path.parent != snap_dir:
        raise ValueError("snapshot_id must be a plain snapshot name inside the workspace snapshots folder.")
    if not path.exists():
        raise ValueError(f"Snapshot '{snapshot_id}' not found.")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {
        "snapshot_id": data.get("snapshot_id") or snapshot_id,
        "taken_at": str(data.get("taken_at") or ""),
        "source": data.get("source", {}) or {},
        "elements": data.get("elements", []),
        "types": data.get("types", []),
        "is_mock": False,
    }


def _qaqc_rules_module() -> Any:
    """Load the QA/QC rule engine by file path so it works however modules are loaded."""
    import importlib.util

    path = Path(__file__).resolve().parent.parent / "qaqc_checker" / "module.py"
    spec = importlib.util.spec_from_file_location("_review_pack_qaqc_rules", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_MAX_CELL_CHARS = 32000  # Excel's hard limit is 32,767


def _chunk_uids(uids: List[str], limit: int = _MAX_CELL_CHARS) -> List[str]:
    """Join UniqueIds with '; ' into strings that each fit in one Excel cell."""
    chunks: List[str] = []
    current: List[str] = []
    size = 0
    for uid in uids:
        add = len(uid) + (2 if current else 0)
        if current and size + add > limit:
            chunks.append("; ".join(current))
            current, size, add = [], 0, len(uid)
        current.append(uid)
        size += add
    if current:
        chunks.append("; ".join(current))
    return chunks


def _review_findings(elements: List[Dict[str, Any]], types: List[Dict[str, Any]], doc_guid: str, rule_pack: str) -> List[Dict[str, Any]]:
    """Run the QA/QC rules in memory (does not touch the issue store), grouped per rule."""
    qaqc = _qaqc_rules_module()

    grouped: List[Dict[str, Any]] = []
    for rule in qaqc._load_rule_pack(rule_pack):
        try:
            hits = qaqc._run_rule(rule, elements, types, doc_guid)
        except Exception as exc:  # a broken rule must not sink the whole pack
            logger.error("Rule '%s' failed: %s", rule.get("id"), exc)
            continue
        if not hits:
            continue
        uids = [h["element_uid"] for h in hits if h.get("element_uid")]
        first_label = hits[0].get("label") or ""
        template = rule.get("fix_template") or ""
        try:
            step = template.format(label=first_label) if template else ""
        except (KeyError, IndexError, ValueError):
            step = template
        grouped.append({
            "severity": rule.get("severity", "info"),
            "rule_id": rule["id"],
            "category": rule.get("category", ""),
            "message": rule.get("description", ""),
            "count": len(hits),
            "uids": uids,
            "next_step": step or "Review the listed elements in Revit and correct them.",
        })
    grouped.sort(key=lambda g: (_SEVERITY_ORDER.get(g["severity"], 9), g["rule_id"]))
    return grouped


class ReportGeneratorModule:

    def export_excel(
        self,
        snapshot_id: str = "",
        element_filter: Dict[str, Any] = None,
        param_names: List[str] = None,
        include_qaqc: bool = True,
        output_filename: str = "model_report.xlsx",
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        elements, types = _get_data(snapshot_id, workspace)
        filter_dsl = element_filter or {}
        param_names = param_names or []

        matched = [el for el in elements if _match_element(el, filter_dsl)]

        wb = openpyxl.Workbook()
        issues = _load_qaqc_issues(workspace) if include_qaqc else []

        ws_summary = wb.active
        ws_summary.title = "Summary"
        _write_summary_sheet(ws_summary, snapshot_id, _load_source(snapshot_id, workspace), len(matched), issues)

        # --- Sheet 1: Elements ---
        ws_el = wb.create_sheet("Elements")
        el_headers = ["UID", "Element ID", "Category", "Family", "Type Name", "Level UID", "Workset"]
        _write_header(ws_el, el_headers)
        for r, el in enumerate(matched, 2):
            ws_el.append([
                el.get("uid", ""),
                el.get("element_id", ""),
                el.get("category", ""),
                el.get("family", ""),
                el.get("type_name", ""),
                el.get("level_uid", ""),
                el.get("workset", ""),
            ])

        # --- Sheet 2: Parameters ---
        if param_names:
            ws_param = wb.create_sheet("Parameters")
            param_headers = ["UID", "Category", "Type Name"] + param_names
            _write_header(ws_param, param_headers)
            for r, el in enumerate(matched, 2):
                row = [el.get("uid", ""), el.get("category", ""), el.get("type_name", "")]
                for pname in param_names:
                    pinfo = (el.get("params", {}) or {}).get(pname)
                    row.append(pinfo.get("v") if pinfo else "")
                ws_param.append(row)

        # --- Sheet 3: Types ---
        ws_types = wb.create_sheet("Types")
        _write_header(ws_types, ["Family", "Type Name", "Category", "Family Source"])
        for t in types:
            ws_types.append([
                t.get("family", ""),
                t.get("type_name", ""),
                t.get("category", ""),
                t.get("family_source", "loadable"),
            ])

        # --- Sheet 4: QA/QC Issues (optional) ---
        if include_qaqc:
            ws_qa = wb.create_sheet("QA_QC Issues")
            qa_headers = ["Issue ID", "Rule ID", "Severity", "Element UID", "Label", "Message", "Status", "Created At"]
            _write_header(ws_qa, qa_headers)
            for r, issue in enumerate(issues, 2):
                ws_qa.append([
                    issue.get("id", ""),
                    issue.get("rule_id", ""),
                    issue.get("severity", ""),
                    issue.get("element_uid", ""),
                    issue.get("label", ""),
                    issue.get("message", ""),
                    issue.get("status", ""),
                    issue.get("created_at", ""),
                ])
                # Color row by severity
                sev = issue.get("severity", "")
                fill_color = SEVERITY_COLORS.get(sev)
                if fill_color:
                    fill = PatternFill("solid", fgColor=fill_color)
                    for col in range(1, len(qa_headers) + 1):
                        ws_qa.cell(row=r, column=col).fill = fill

        # --- Save ---
        out_path = _ws_dir(workspace) / output_filename
        wb.save(str(out_path))

        return {
            "status": "exported",
            "output_file": str(out_path),
            "element_count": len(matched),
            "type_count": len(types),
            "sheets": wb.sheetnames,
        }

    def build_review_pack(
        self,
        snapshot_id: str = "",
        rule_pack: str = "core",
        output_filename: str = "model_review.xlsx",
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        """Build one 'Model review' workbook: Cover, Findings, Counts by category, What to do next."""
        from datetime import datetime, timezone
        from revit_mcp_server.security.workspace import WorkspaceMonitor

        data = _load_review_snapshot(snapshot_id, workspace)
        elements, types, source = data["elements"], data["types"], data["source"]
        doc_guid = source.get("doc_guid") or data["snapshot_id"]
        findings = _review_findings(elements, types, doc_guid, rule_pack)

        out_path = WorkspaceMonitor(workspace.allowed_directories).assert_in_workspace(
            _ws_dir(workspace) / output_filename
        )
        if out_path.suffix.lower() != ".xlsx":
            raise ValueError("output_filename must end in .xlsx")

        wb = openpyxl.Workbook()

        # --- Cover ---
        ws = wb.active
        ws.title = "Cover"
        flagged_uids = {u for f in findings for u in f["uids"]}
        total_hits = len(flagged_uids)
        label = "MOCK data - generated sample, not a live Revit model" if data["is_mock"] else "Snapshot taken from the model"
        rows = [
            ("Document", source.get("doc_title") or source.get("title") or ""),
            ("Document GUID", source.get("doc_guid", "")),
            ("Snapshot ID", data["snapshot_id"]),
            ("Snapshot time", data["taken_at"]),
            ("Data source", "mock" if data["is_mock"] else "real"),
            ("Data source note", label),
            ("Review generated (UTC)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
            ("Rule pack", rule_pack),
            ("Elements reviewed", len(elements)),
            ("Rules with findings", len(findings)),
            ("Elements flagged", total_hits),
        ]
        _write_header(ws, ["Item", "Value"])
        ws.column_dimensions["A"].width = 26
        ws.column_dimensions["B"].width = 60
        for row in rows:
            ws.append(list(row))

        # --- Findings ---
        ws_f = wb.create_sheet("Findings")
        f_headers = ["Severity", "Rule", "Category", "What is wrong", "Elements affected", "UniqueIds", "Next step"]
        _write_header(ws_f, f_headers)
        for width, col in zip((12, 24, 14, 50, 12, 60, 50), "ABCDEFG"):
            ws_f.column_dimensions[col].width = width
        r = 1
        for f in findings:
            # An Excel cell holds at most 32,767 characters; continue long UniqueId
            # lists on extra rows so no id is silently dropped.
            chunks = _chunk_uids(f["uids"]) or [""]
            for i, chunk in enumerate(chunks):
                r += 1
                if i == 0:
                    ws_f.append([f["severity"], f["rule_id"], f["category"], f["message"], f["count"], chunk, f["next_step"]])
                else:
                    ws_f.append([f["severity"], f["rule_id"], f["category"], f["message"] + " (UniqueIds continued)", "", chunk, ""])
                color = SEVERITY_COLORS.get(f["severity"])
                if color:
                    for col in range(1, len(f_headers) + 1):
                        ws_f.cell(row=r, column=col).fill = PatternFill("solid", fgColor=color)

        # --- Counts by category ---
        ws_c = wb.create_sheet("Counts by category")
        _write_header(ws_c, ["Category", "Elements", "Flagged by rules"])
        ws_c.column_dimensions["A"].width = 30
        cat_total: Dict[str, int] = {}
        cat_flagged: Dict[str, int] = {}
        for el in elements:
            cat = el.get("category") or "(none)"
            cat_total[cat] = cat_total.get(cat, 0) + 1
            if el.get("uid") in flagged_uids:
                cat_flagged[cat] = cat_flagged.get(cat, 0) + 1
        for cat in sorted(cat_total):
            ws_c.append([cat, cat_total[cat], cat_flagged.get(cat, 0)])

        # --- What to do next ---
        ws_n = wb.create_sheet("What to do next")
        _write_header(ws_n, ["Priority", "Action", "Why", "Elements"])
        for col, width in zip("ABCD", (16, 60, 50, 10)):
            ws_n.column_dimensions[col].width = width
        if data["is_mock"]:
            ws_n.append(["Note", "Capture a real snapshot of the open model and run this again.", "This pack was built from generated sample data.", ""])
        if not findings:
            ws_n.append(["Done", "No rule findings. Nothing to fix from this rule pack.", "", ""])
        for f in findings:
            ws_n.append([_SEVERITY_LABEL.get(f["severity"], f["severity"]), f["next_step"], f["message"], f["count"]])

        wb.save(str(out_path))

        return {
            "status": "exported",
            "output_file": str(out_path),
            "data_source": "mock" if data["is_mock"] else "real",
            "snapshot_id": data["snapshot_id"],
            "element_count": len(elements),
            "finding_rules": len(findings),
            "sheets": wb.sheetnames,
        }

    def export_sqlite_summary(
        self,
        snapshot_id: str = "",
        output_filename: str = "model_data.db",
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        elements, types = _get_data(snapshot_id, workspace)
        out_path = _ws_dir(workspace) / output_filename

        conn = sqlite3.connect(str(out_path))
        conn.executescript("""
            DROP TABLE IF EXISTS elements;
            DROP TABLE IF EXISTS types;
            CREATE TABLE elements (
                uid TEXT PRIMARY KEY,
                element_id TEXT,
                category TEXT,
                family TEXT,
                type_name TEXT,
                level_uid TEXT,
                workset TEXT,
                host_uid TEXT
            );
            CREATE TABLE types (
                family TEXT,
                type_name TEXT,
                category TEXT,
                family_source TEXT
            );
        """)

        conn.executemany(
            "INSERT OR REPLACE INTO elements VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    el.get("uid", ""),
                    el.get("element_id", ""),
                    el.get("category", ""),
                    el.get("family", ""),
                    el.get("type_name", ""),
                    el.get("level_uid", ""),
                    el.get("workset", ""),
                    el.get("host_uid", ""),
                )
                for el in elements
            ]
        )

        conn.executemany(
            "INSERT INTO types VALUES (?,?,?,?)",
            [
                (
                    t.get("family", ""),
                    t.get("type_name", ""),
                    t.get("category", ""),
                    t.get("family_source", "loadable"),
                )
                for t in types
            ]
        )

        conn.commit()
        conn.close()

        return {
            "status": "exported",
            "output_file": str(out_path),
            "element_count": len(elements),
            "type_count": len(types),
        }
