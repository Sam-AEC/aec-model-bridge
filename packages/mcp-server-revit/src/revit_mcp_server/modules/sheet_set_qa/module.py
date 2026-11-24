"""
sheet_set_qa module - read-only sheet checks before a drawing issue, over a saved snapshot.

Command:
  check - duplicate and equivalent sheet numbers within a prefix, gaps in the numbering inside
          a series, missing title block fields, sheets with no placed views, and sheet numbers
          or names that do not fully match a pattern. Findings carry a severity. Optional CSV.

Why a module and not a QA/QC rule pack: rule packs filter and assert on single element
records. These checks compare sheets with each other (duplicates, sequence) and need the
sheet/view placement lists, which the rule engine does not read.

Snapshot data is read the same way as sheet_view_audit (top-level ``sheets``/``views`` lists,
or ViewSheet element records). A check the snapshot cannot support is reported under
``checks`` as ``not_enough_data`` and the status is ``partial``; it is never reported as passed.
A snapshot with no sheets returns ``no_sheet_data``.

Sheet numbers are split into prefix, number and sub-suffix: ``A-101.1`` is prefix ``A-``,
number 101, suffix ``.1``. Prefixes are compared without case and trailing separators, so
``A-101`` and ``A101`` share prefix ``A`` and are reported as equivalent numbers.
"""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from revit_mcp_server.security.module_permissions import writable_path

DEFAULT_REQUIRED_FIELDS = ["Sheet Number", "Sheet Name", "Drawn By", "Checked By", "Sheet Issue Date"]
# Letters, optional separator, digits, optional ".N" sub-number, optional letter suffix.
DEFAULT_NUMBER_PATTERN = r"[A-Za-z]{1,4}[-_. ]?\d{1,4}(?:\.\d{1,3})?[A-Za-z]?"
# No leading or trailing whitespace, not empty, not the Revit default name "Unnamed".
DEFAULT_NAME_PATTERN = r"(?!(?i:unnamed)$)\S(?:.*\S)?"
DEFAULT_SERIES_SIZE = 100
MAX_PATTERN_LENGTH = 500
MAX_SHEETS_PER_FINDING = 200
MAX_GAP_NUMBERS = 50

_SEV_ORDER = {"error": 0, "warning": 1, "info": 2}
_NUMBER_PARTS = re.compile(r"^(?P<prefix>.*?)(?P<num>\d+)(?P<sub>(?:\.\d+)?[A-Za-z]?)$")
_FIELD_ALIASES = {"issue date": "sheet issue date"}


def _sibling(module_id: str) -> Any:
    """Load another module's module.py by file path (the server loads modules as plain modules)."""
    path = Path(__file__).resolve().parent.parent / module_id / "module.py"
    spec = importlib.util.spec_from_file_location(f"_sheet_set_qa_{module_id}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sva = _sibling("sheet_view_audit")


def split_number(number: Any) -> Optional[Tuple[str, str, int, str, str]]:
    """(prefix key, prefix as written, number, suffix, digits as written), or None without digits."""
    text = str(number or "").strip()
    m = _NUMBER_PARTS.match(text)
    if not m:
        return None
    raw = m.group("prefix")
    return raw.rstrip("-_. ").upper(), raw, int(m.group("num")), m.group("sub").lower(), m.group("num")


def _compile(pattern: Optional[str], default: str, label: str) -> Optional[re.Pattern]:
    if pattern is None:
        pattern = default
    if not isinstance(pattern, str):
        raise ValueError(f"{label} must be text (a regular expression).")
    if pattern == "":
        return None
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise ValueError(f"{label} is longer than {MAX_PATTERN_LENGTH} characters.")
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"{label} is not a valid regular expression: {exc}") from None


def _field_key(name: str) -> str:
    key = str(name).strip().lower()
    return _FIELD_ALIASES.get(key, key)


def _field_present(sheet: Dict[str, Any], field: str) -> bool:
    key = _field_key(field)
    if key in ("sheet number", "number", "sheet name", "name"):
        return True
    return any(_field_key(k) == key for k in (sheet.get("params") or {}))


def _field_value(sheet: Dict[str, Any], field: str) -> Any:
    key = _field_key(field)
    if key in ("sheet number", "number"):
        return sheet.get("number")
    if key in ("sheet name", "name"):
        return sheet.get("name")
    for k, v in (sheet.get("params") or {}).items():
        if _field_key(k) == key:
            return v.get("v") if isinstance(v, dict) else v
    return None


def _blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _ref(sheet: Dict[str, Any], detail: str = "") -> Dict[str, Any]:
    ref = {"uid": sheet.get("uid"), "number": str(sheet.get("number") or ""), "name": str(sheet.get("name") or "")}
    if detail:
        ref["detail"] = detail
    return ref


def _label(sheet: Dict[str, Any]) -> str:
    return f"{sheet.get('number') or '?'} {sheet.get('name') or ''}".strip()


def _preview(items: List[str], limit: int = 5) -> str:
    return ", ".join(items[:limit]) + ("..." if len(items) > limit else "")


def _finding(check: str, severity: str, message: str, sheets: List[Dict[str, Any]], next_step: str,
             **extra: Any) -> Dict[str, Any]:
    return {
        "check": check, "severity": severity, "message": message,
        "sheet_count": len(sheets), "sheets": sheets[:MAX_SHEETS_PER_FINDING],
        "unique_ids": sorted({s["uid"] for s in sheets if s.get("uid")}),
        "next_step": next_step, **extra,
    }


def _gap_text(raw_prefix: str, lo: int, hi: int, width: int) -> str:
    a = f"{raw_prefix}{lo:0{width}d}"
    return a if lo == hi else f"{a} to {raw_prefix}{hi:0{width}d}"


def check_sheets(
    sheets: List[Dict[str, Any]],
    all_sheets: List[Dict[str, Any]],
    views: List[Dict[str, Any]],
    enabled: Dict[str, bool],
    required_fields: List[str],
    number_re: Optional[re.Pattern],
    name_re: Optional[re.Pattern],
    series_size: int,
) -> Dict[str, Any]:
    """Run the enabled checks. Pure over sheet/view records; ``all_sheets`` is used for duplicates."""
    findings: List[Dict[str, Any]] = []
    field_report: Dict[str, str] = {}
    selected = {id(s) for s in sheets}

    # Duplicates: exact text (error) and equivalent forms such as A-101 / A101 (warning).
    if enabled["duplicate_sheet_numbers"]:
        exact: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        equiv: Dict[Tuple[str, int, str], List[Dict[str, Any]]] = defaultdict(list)
        for s in all_sheets:
            num = str(s.get("number") or "").strip()
            if not num:
                continue
            exact[num.lower()].append(s)
            parts = split_number(num)
            if parts:
                equiv[(parts[0], parts[2], parts[3])].append(s)
        dupes = [g for g in exact.values() if len(g) > 1 and any(id(s) in selected for s in g)]
        if dupes:
            findings.append(_finding(
                "duplicate_sheet_numbers", "error",
                f"{len(dupes)} sheet number(s) are used more than once: " + _preview([str(g[0].get("number")) for g in dupes]),
                [_ref(s) for g in dupes for s in g],
                "Renumber the duplicate sheets so every sheet number is unique before the issue.",
            ))
        alike = [g for g in equiv.values()
                 if len({str(s.get("number")).strip().lower() for s in g}) > 1 and any(id(s) in selected for s in g)]
        if alike:
            findings.append(_finding(
                "equivalent_sheet_numbers", "warning",
                f"{len(alike)} sheet number(s) differ only in separator or case: "
                + _preview([" / ".join(sorted({str(s.get('number')) for s in g})) for g in alike]),
                [_ref(s) for g in alike for s in g],
                "Use one numbering form within each prefix so these do not read as the same sheet.",
            ))

    # Gaps inside a numbering series, per prefix.
    if enabled["non_sequential_numbers"]:
        groups: Dict[str, Dict[int, List[Tuple[str, int]]]] = defaultdict(lambda: defaultdict(list))
        raw_prefix: Dict[str, str] = {}
        unparsed: List[Dict[str, Any]] = []
        for s in sheets:
            parts = split_number(s.get("number"))
            if parts is None:
                if not _blank(s.get("number")):
                    unparsed.append(_ref(s))
                continue
            key, raw, num, _sub, digits = parts
            raw_prefix.setdefault(key, raw)
            groups[key][num // series_size].append((digits, num))
        gaps: List[Dict[str, Any]] = []
        for key in sorted(groups):
            for series in sorted(groups[key]):
                nums = sorted({n for _, n in groups[key][series]})
                width = min(len(d) for d, _ in groups[key][series])
                for a, b in zip(nums, nums[1:]):
                    if b - a > 1:
                        gaps.append({
                            "prefix": raw_prefix[key] or "(none)", "after": f"{raw_prefix[key]}{a:0{width}d}",
                            "before": f"{raw_prefix[key]}{b:0{width}d}", "missing_count": b - a - 1,
                            "missing": _gap_text(raw_prefix[key], a + 1, b - 1, width),
                        })
        if gaps:
            findings.append(_finding(
                "non_sequential_numbers", "info",
                f"{len(gaps)} gap(s) in the sheet numbering within a series: " + _preview([g["missing"] for g in gaps]),
                [], "Check that no sheet is missing from the set. Ignore the gap if the numbers are reserved on purpose.",
                gaps=gaps[:MAX_GAP_NUMBERS], gap_count=len(gaps),
            ))
        if unparsed:
            findings.append(_finding(
                "unparsed_sheet_numbers", "info",
                f"{len(unparsed)} sheet number(s) have no digits, so they were left out of the sequence check: "
                + _preview([r["number"] for r in unparsed]),
                unparsed, "Give these sheets a numbered sheet number if they belong in the sequence.",
            ))

    # Required title block fields.
    for field in required_fields if enabled["missing_required_fields"] else []:
        if not any(_field_present(s, field) for s in sheets):
            field_report[field] = "not_captured"
            findings.append(_finding(
                "field_not_found", "warning",
                f"No sheet in the snapshot carries '{field}'. Either the snapshot did not capture it or the project "
                "has no such parameter, so it was NOT checked.",
                [], f"Check the parameter name, or take a new snapshot that includes '{field}' on sheets.",
                field=field,
            ))
            continue
        missing = [_ref(s) for s in sheets if _blank(_field_value(s, field))]
        field_report[field] = "ran"
        if missing:
            findings.append(_finding(
                "missing_required_field", "warning",
                f"{len(missing)} sheet(s) have an empty '{field}': " + _preview([f"{r['number']} {r['name']}".strip() for r in missing]),
                missing, f"Fill in '{field}' on these sheets before the issue.", field=field,
            ))

    # Sheets with no placed views. Placeholder sheets hold no views by design.
    if enabled["sheets_without_views"]:
        on_sheet = {v.get("sheet_uid") for v in views if v.get("sheet_uid")}
        empty = [_ref(s) for s in sheets
                 if not s.get("is_placeholder") and not (s.get("view_uids") or []) and s.get("uid") not in on_sheet]
        if empty:
            findings.append(_finding(
                "sheets_without_views", "warning",
                f"{len(empty)} sheet(s) have no views placed on them: " + _preview([f"{r['number']} {r['name']}".strip() for r in empty]),
                empty, "Place the views on these sheets, or take them out of the issue set.",
            ))

    # Patterns.
    for check, rx, getter, what in (
        ("number_pattern_mismatch", number_re, lambda s: s.get("number"), "number"),
        ("name_pattern_mismatch", name_re, lambda s: s.get("name"), "name"),
    ):
        if rx is None or not enabled[check]:
            continue
        bad = [_ref(s) for s in sheets if not rx.fullmatch(str(getter(s) or ""))]
        if bad:
            findings.append(_finding(
                check, "warning",
                f"{len(bad)} sheet {what}(s) do not match the pattern {rx.pattern!r}: "
                + _preview([repr(str(getter(s) or "")) for s in sheets if not rx.fullmatch(str(getter(s) or ""))]),
                bad, f"Rename these sheets to match the office sheet {what} pattern, or pass a different {what}_pattern.",
                pattern=rx.pattern,
            ))

    findings.sort(key=lambda f: _SEV_ORDER[f["severity"]])
    return {"findings": findings, "fields": field_report}


def _csv_text(findings: List[Dict[str, Any]]) -> str:
    def cell(v: Any) -> Any:
        # A leading = + - @ would be run as a formula by a spreadsheet; names come from the model.
        return "'" + v if isinstance(v, str) and v[:1] in "=+-@" else v

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["severity", "check", "sheet_number", "sheet_name", "unique_id", "detail", "next_step"])
    for f in findings:
        rows = [[s["number"], s["name"], s.get("uid") or "", s.get("detail", "")] for s in f["sheets"]]
        if f.get("gaps"):
            rows = [[g["missing"], "", "", f"missing between {g['after']} and {g['before']}"] for g in f["gaps"]]
        if not rows:
            rows = [["", "", "", f["message"]]]
        for r in rows:
            writer.writerow([cell(v) for v in [f["severity"], f["check"], *r, f["next_step"]]])
    return out.getvalue()


class SheetSetQaModule:
    def check(
        self,
        snapshot_id: str = "",
        sheet_numbers: Optional[List[str]] = None,
        required_fields: Optional[List[str]] = None,
        number_pattern: Optional[str] = None,
        name_pattern: Optional[str] = None,
        series_size: int = DEFAULT_SERIES_SIZE,
        csv_filename: str = "",
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        if not snapshot_id:
            raise ValueError("sheet_set_qa_check needs a snapshot_id. Take a snapshot first and pass its id.")
        number_re = _compile(number_pattern, DEFAULT_NUMBER_PATTERN, "number_pattern")
        name_re = _compile(name_pattern, DEFAULT_NAME_PATTERN, "name_pattern")
        try:
            series_size = DEFAULT_SERIES_SIZE if series_size is None else int(series_size)
        except (TypeError, ValueError):
            raise ValueError("series_size must be a whole number.") from None
        if not 1 <= series_size <= 100000:
            raise ValueError("series_size must be between 1 and 100000.")
        if csv_filename and not (isinstance(csv_filename, str) and csv_filename.lower().endswith(".csv")):
            raise ValueError("csv_filename must end in .csv")
        required = DEFAULT_REQUIRED_FIELDS if required_fields is None else [str(f) for f in required_fields if str(f).strip()]

        from revit_mcp_server.security.safe_paths import snapshot_file

        path = snapshot_file(Path(workspace.allowed_directories[0]) / "snapshots", snapshot_id)
        if not path.exists():
            raise ValueError(f"Snapshot '{snapshot_id}' not found.")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        explicit = isinstance(data.get("sheets"), list)
        if explicit:
            all_sheets = [s for s in data["sheets"] if isinstance(s, dict)]
            views = [v for v in (data.get("views") or []) if isinstance(v, dict)]
            source = "top-level sheets/views lists"
        else:
            all_sheets, views = sva.derive_from_elements(data.get("elements") or [])
            views = []  # drafting-view records say nothing about placement
            source = "ViewSheet element records"
        counts = data.get("counts") or {}
        partial_capture = bool(counts.get("sheets_truncated") or counts.get("truncated") or counts.get("categories")
                               or counts.get("dirty_only") or data.get("dirty_only"))

        base = {"read_only": True, "snapshot_id": snapshot_id, "data_source": source}
        if not all_sheets:
            msg = ("This snapshot has no sheets in it, so nothing was checked (not even 'no problems found'). "
                   "Take a full snapshot of a project that has sheets.")
            if partial_capture:
                msg += " The snapshot is truncated, category-filtered or dirty-only, which may be why."
            return {**base, "status": "no_sheet_data", "message": msg, "total_findings": 0, "findings": []}

        sheets = all_sheets
        requested_missing: List[str] = []
        if sheet_numbers:
            wanted = {str(n).strip().lower(): str(n).strip() for n in sheet_numbers if str(n).strip()}
            sheets = [s for s in all_sheets if str(s.get("number") or "").strip().lower() in wanted]
            have = {str(s.get("number") or "").strip().lower() for s in sheets}
            requested_missing = [orig for key, orig in wanted.items() if key not in have]

        placement_known = explicit and (
            all("view_uids" in s for s in all_sheets)
            or (isinstance(data.get("views"), list) and bool(views) and all("sheet_uid" in v for v in views))
        )
        support = {
            "duplicate_sheet_numbers": (True, ""),
            "non_sequential_numbers": (True, ""),
            "missing_required_fields": (bool(required), "No required fields were given."),
            "sheets_without_views": (
                placement_known,
                "The snapshot does not say which views are placed on which sheet (view_uids per sheet or "
                "sheet_uid per view), so sheets without views cannot be found.",
            ),
            "number_pattern_mismatch": (number_re is not None, "number_pattern is empty, so the check is off."),
            "name_pattern_mismatch": (name_re is not None, "name_pattern is empty, so the check is off."),
        }
        enabled = {k: ok for k, (ok, _) in support.items()}
        result = check_sheets(sheets, all_sheets, views, enabled, required, number_re, name_re, series_size)
        findings = result["findings"]
        if requested_missing:
            findings.insert(0, _finding(
                "requested_sheet_missing", "error",
                f"{len(requested_missing)} sheet number(s) in the issue set are not in the snapshot: "
                + _preview(requested_missing),
                [{"uid": None, "number": n, "name": ""} for n in requested_missing],
                "Create these sheets, correct the numbers in the issue set, or take a new snapshot.",
            ))

        checks: Dict[str, Dict[str, Any]] = {}
        for k, (ok, why) in support.items():
            if ok:
                checks[k] = {"status": "ran"}
            elif k in ("number_pattern_mismatch", "name_pattern_mismatch") or (k == "missing_required_fields" and not required):
                checks[k] = {"status": "off", "reason": why}
            else:
                checks[k] = {"status": "not_enough_data", "reason": why}
        not_captured = [f for f, st in result["fields"].items() if st == "not_captured"]
        if not_captured and "missing_required_fields" in checks and checks["missing_required_fields"]["status"] == "ran":
            checks["missing_required_fields"] = {
                "status": "partial", "not_captured": not_captured,
                "reason": "These fields are on no sheet in the snapshot and were not checked: " + ", ".join(not_captured),
            }

        messages: List[str] = []
        skipped = [k for k, c in checks.items() if c["status"] in ("not_enough_data", "partial")]
        status = "ok"
        if skipped:
            status = "partial"
            messages.append("Not enough data in this snapshot for: " + ", ".join(skipped)
                            + ". Those checks were NOT fully run, so zero findings for them does not mean they pass. "
                            "Details are under 'checks'.")
        if partial_capture:
            status = "partial"
            messages.append("The snapshot capture was truncated, category-filtered or dirty-only; findings cover only the captured sheets.")

        files: Dict[str, str] = {}
        if csv_filename:
            rg = _sibling("report_generator")
            out = writable_path(workspace, rg._confined(workspace, csv_filename))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(_csv_text(findings), encoding="utf-8")
            files["csv_file"] = str(out)

        by_prefix: Dict[str, int] = defaultdict(int)
        for s in sheets:
            parts = split_number(s.get("number"))
            by_prefix[(parts[0] or "(none)") if parts else "(no digits)"] += 1
        return {
            **base,
            "status": status,
            "message": " ".join(messages) if messages else "All checks ran on the sheets in the snapshot.",
            "ready_for_issue": status == "ok" and not any(f["severity"] in ("error", "warning") for f in findings),
            "sheet_count": len(sheets),
            "sheets_in_snapshot": len(all_sheets),
            "sheets_per_prefix": dict(sorted(by_prefix.items())),
            "required_fields": required,
            "number_pattern": number_re.pattern if number_re else "",
            "name_pattern": name_re.pattern if name_re else "",
            "series_size": series_size,
            "total_findings": len(findings),
            "by_severity": {sev: sum(1 for f in findings if f["severity"] == sev) for sev in _SEV_ORDER},
            "checks": checks,
            "findings": findings,
            **files,
        }
