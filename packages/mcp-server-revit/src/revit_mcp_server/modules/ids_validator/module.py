"""
ids_validator module - check an IFC file against a buildingSMART IDS file.

Command:
  validate_ifc - Open an .ifc and an .ids from the workspace, run every IDS specification with
                 ifctester (IfcOpenShell), and return per-specification pass/fail with the
                 GlobalIds of failing entities (capped, with the full count). Optionally writes
                 an HTML report and a JSON summary inside the workspace.

Read-only: the IFC and IDS files are only read. ifctester is an optional extra
(``pip install "aec-model-bridge[ids]"``); without it the tool refuses with that hint.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_MAX_FAILED = 50
MAX_FAILED = 500
MAX_REASONS = 5
MAX_IDS_BYTES = 10_000_000
INSTALL_HINT = (
    "IDS validation needs the optional ifctester package. Install it with "
    "pip install \"aec-model-bridge[ids]\" (or uv sync --extra ids) and restart the server."
)


def _sibling(module_id: str) -> Any:
    path = Path(__file__).resolve().parent.parent / module_id / "module.py"
    spec = importlib.util.spec_from_file_location(f"_ids_validator_{module_id}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rg = _sibling("report_generator")


def _input_file(workspace: Any, name: str, suffix: str, what: str) -> Path:
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{what} is required: a workspace path ending in {suffix}")
    path = rg._confined(workspace, name)
    if path.suffix.lower() != suffix:
        raise ValueError(f"{what} must end in {suffix}")
    if not path.is_file():
        raise ValueError(f"{what} '{name}' was not found in the workspace.")
    return path


def _entity(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "global_id": row.get("global_id") or f"#{row.get('id')}",
        "class": row.get("class"),
        "name": row.get("name"),
    }


def summarise(results: Dict[str, Any], max_failed: int) -> List[Dict[str, Any]]:
    """Per-specification rows from ifctester's JSON-reporter results."""
    out: List[Dict[str, Any]] = []
    for spec in results.get("specifications", []):
        failed: Dict[Any, Dict[str, Any]] = {}
        requirements = []
        for req in spec.get("requirements", []):
            requirements.append({
                "requirement": req.get("description") or req.get("label"),
                "passed": req.get("total_pass"), "failed": req.get("total_fail"),
            })
            for ent in req.get("failed_entities", []):
                key = ent.get("id")
                row = failed.setdefault(key, {**_entity(ent), "reasons": []})
                reason = f"{req.get('label')}: {ent.get('reason')}" if ent.get("reason") else str(req.get("label"))
                if reason not in row["reasons"] and len(row["reasons"]) < MAX_REASONS:
                    row["reasons"].append(reason)
        skipped = bool(spec.get("is_skipped")) or spec.get("is_ifc_version") is False
        status = "skipped" if skipped else ("pass" if spec.get("status") else "fail")
        rows = list(failed.values())
        out.append({
            "name": spec.get("name"),
            "status": status,
            "applicable": spec.get("total_applicable"),
            "applicable_passed": spec.get("total_applicable_pass"),
            "applicable_failed": spec.get("total_applicable_fail"),
            "cardinality": spec.get("cardinality"),
            "requirements": requirements,
            "failed_entities_total": len(rows),
            "failed_entities_shown": min(len(rows), max_failed),
            "failed_entities": rows[:max_failed],
            "note": ("Not run: the specification is for another IFC schema version than this file." if skipped else
                     "No entity matched the applicability, which fails a required specification."
                     if status == "fail" and not spec.get("total_applicable") else ""),
        })
    return out


class IdsValidatorModule:
    def validate_ifc(
        self,
        ifc_path: str = "",
        ids_path: str = "",
        max_failed: int = DEFAULT_MAX_FAILED,
        html_filename: str = "",
        json_filename: str = "",
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        try:
            import ifcopenshell
            from ifctester import ids as ids_mod
            from ifctester import reporter
        except ImportError as exc:
            raise ValueError(INSTALL_HINT) from exc
        max_failed = max(1, min(int(max_failed or DEFAULT_MAX_FAILED), MAX_FAILED))
        for name, suffix in ((html_filename, ".html"), (json_filename, ".json")):
            if name and not name.lower().endswith(suffix):
                raise ValueError(f"The report file name must end in {suffix}")
        ifc_file = _input_file(workspace, ifc_path, ".ifc", "ifc_path")
        ids_file = _input_file(workspace, ids_path, ".ids", "ids_path")
        if ids_file.stat().st_size > MAX_IDS_BYTES:
            raise ValueError("The IDS file is too large.")
        try:
            spec = ids_mod.open(str(ids_file), validate=True)
        except Exception as exc:  # malformed XML or a file that breaks the IDS schema
            raise ValueError(f"The IDS file is not a valid IDS document: {exc}") from exc
        try:
            model = ifcopenshell.open(str(ifc_file))
        except Exception as exc:
            raise ValueError(f"The IFC file could not be read: {exc}") from exc
        spec.validate(model)
        json_reporter = reporter.Json(spec)
        json_reporter.report()
        results = json_reporter.results
        specs = summarise(results, max_failed)
        counts = {s: sum(1 for x in specs if x["status"] == s) for s in ("pass", "fail", "skipped")}
        summary_text = (
            f"{counts['pass']} of {len(specs)} specifications pass, {counts['fail']} fail"
            + (f", {counts['skipped']} skipped" if counts["skipped"] else "") + "."
        )
        notes = [f"Failing entities are capped at {max_failed} per specification; the totals are complete."]
        if not specs:
            notes.append("The IDS file has no specifications.")
        result: Dict[str, Any] = {
            "read_only": True,
            "ifc_file": str(ifc_file),
            "ids_file": str(ids_file),
            "ids_title": results.get("title"),
            "ifc_schema": model.schema,
            "passed": bool(results.get("status")) and counts["fail"] == 0,
            "specifications_total": len(specs),
            "specifications_passed": counts["pass"],
            "specifications_failed": counts["fail"],
            "specifications_skipped": counts["skipped"],
            "summary": summary_text,
            "specifications": specs,
            "notes": notes,
        }
        if json_filename:
            path = rg._confined(workspace, json_filename)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
            result["json_file"] = str(path)
        if html_filename:
            html_reporter = reporter.Html(spec)
            html_reporter.report()
            path = rg._confined(workspace, html_filename)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(html_reporter.to_string(), encoding="utf-8")
            result["html_file"] = str(path)
        return result
