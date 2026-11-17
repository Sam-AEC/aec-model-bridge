"""
qa_handover module - a compact QA and change report a BIM coordinator can hand over.

Command:
  build_report  - Summarise a saved snapshot (rule findings grouped per rule), optionally
                  re-check it against a later snapshot, and optionally list the approved
                  parameter changes from plan proof bundles. Writes
                  ``reports/<name>.json`` and ``reports/<name>.md`` in the workspace and
                  returns only a short summary.

Read-only and built only from saved data: snapshots, a rule pack and ``proofs/<plan_id>.json``.
Anything it cannot prove goes into the report's ``not_verified`` list. Rule evaluation,
snapshot loading and the path guard are reused from report_generator; the snapshot
comparison from model_changes.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from revit_mcp_server.security import proof as proof_mod


def _sibling(module_id: str) -> Any:
    """Load another module's module.py by file path: the server registers modules as plain
    modules, so a normal package import of a sibling fails there."""
    path = Path(__file__).resolve().parent.parent / module_id / "module.py"
    spec = importlib.util.spec_from_file_location(f"_qa_handover_{module_id}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rg = _sibling("report_generator")
_changes = _sibling("model_changes")
_parse_time, compare_snapshot_data = _changes._parse_time, _changes.compare_snapshot_data

SCHEMA = "amb.qa_handover/1"
MAX_REPORT_BYTES = 512_000
FIELD_LIMIT = 120
MAX_IDS = 30
MAX_RULES = 100
MAX_PLANS = 20
MAX_CHANGES = 25
_NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _s(value: Any, limit: int = FIELD_LIMIT) -> Any:
    """Strings: one line, at most ``limit`` characters. Other values pass unchanged."""
    if not isinstance(value, str):
        return value
    text = " ".join(value.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _same(a: Any, b: Any) -> bool:
    return a == b or str(a).strip() == str(b).strip()


def _identity(data: Dict[str, Any]) -> Dict[str, Any]:
    src = data["source"]
    return {
        "snapshot_id": _s(data["snapshot_id"]),
        "taken_at": _s(data["taken_at"]),
        "app": _s(src.get("app") or ""),
        "app_version": _s(src.get("app_version") or ""),
        "element_count": len(data["elements"]),
    }


def _doc_guid(data: Dict[str, Any]) -> str:
    return data["source"].get("doc_guid") or ""


def _is_partial(data: Dict[str, Any]) -> bool:
    coverage = data.get("counts") or {}
    return bool(data.get("dirty_only") or coverage.get("dirty_only")
                or coverage.get("truncated") or coverage.get("categories"))


def _run_rules(data: Dict[str, Any], rule_pack: str, workspace: Any, label: str, not_verified: List[str]):
    failed: List[str] = []
    groups = rg._review_findings(
        data["elements"], data["types"], _doc_guid(data) or data["snapshot_id"], rule_pack, workspace, failed
    )
    if failed:
        not_verified.append(f"{label}: these rules could not run, so their result is unknown: {', '.join(map(str, failed))}.")
    if _is_partial(data):
        not_verified.append(f"{label}: the snapshot is a partial capture; elements that were not captured were not checked.")
    return groups, failed


def _rule_pack_info(rule_pack: str, workspace: Any) -> Dict[str, Any]:
    qaqc = rg._qaqc_rules_module()
    path = qaqc._resolve_pack_path(rule_pack, workspace)
    builtin = path.resolve().is_relative_to(qaqc.RULES_DIR.resolve())
    return {
        "name": rule_pack,
        "origin": "builtin" if builtin else "workspace",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "rules": len(qaqc._load_rule_pack(rule_pack, workspace)),
        "note": "Rule packs have no version field; the pack is identified by name and file SHA-256.",
    }


def _findings(groups: List[Dict[str, Any]], max_ids: int, not_verified: List[str]) -> List[Dict[str, Any]]:
    if len(groups) > MAX_RULES:
        not_verified.append(f"Only the first {MAX_RULES} of {len(groups)} rules with findings are listed.")
    return [
        {
            "rule_id": _s(g["rule_id"]), "severity": g["severity"], "category": _s(g["category"]),
            "message": _s(g["message"]), "count": g["count"], "element_ids": [_s(u) for u in g["uids"][:max_ids]],
            "more": max(0, len(g["uids"]) - max_ids), "next_step": _s(g["next_step"]),
        }
        for g in groups[:MAX_RULES]
    ]


def _verification(before, after, failed_before, failed_after, not_verified) -> Dict[str, Any]:
    """Compare finding identities, keeping failed rules and unidentified hits unknown."""
    b = {g["rule_id"]: g for g in before}
    a = {g["rule_id"]: g for g in after}
    per_rule = []
    for rid in sorted(b.keys() | a.keys() | set(failed_before) | set(failed_after)):
        old, new = b.get(rid, {}), a.get(rid, {})
        old_count = None if rid in failed_before else old.get("count", 0)
        new_count = None if rid in failed_after else new.get("count", 0)
        old_ids, new_ids = set(old.get("uids", [])), set(new.get("uids", []))
        known = old_count is not None and new_count is not None
        identified = known and len(old_ids) == old_count and len(new_ids) == new_count
        if known and not identified:
            not_verified.append(f"Rule {rid}: finding identities are incomplete; resolved and new counts are unknown.")
        per_rule.append({
            "rule_id": _s(rid), "before": old_count, "after": new_count,
            "resolved": len(old_ids - new_ids) if identified else None,
            "new": len(new_ids - old_ids) if identified else None,
        })

    def total(field):
        return None if any(x[field] is None for x in per_rule) else sum(x[field] for x in per_rule)

    return {
        "before_total": total("before"), "after_total": total("after"),
        "resolved": total("resolved"), "new": total("new"), "per_rule": per_rule[:MAX_RULES],
    }


def _after_value(index: Dict[Any, Dict[str, Any]], uid: Any, parameter: Any):
    """(found, value) of one parameter in the after snapshot."""
    p = ((index.get(uid) or {}).get("params") or {}).get(parameter)
    if p is None:
        return False, None
    return True, p.get("v") if isinstance(p, dict) else p


def _plan(plan_id: str, bundle: Dict[str, Any], before: Dict[str, Any], after: Optional[Dict[str, Any]],
          not_verified: List[str]) -> Dict[str, Any]:
    entries = bundle.get("elements") or []
    ran = _parse_time(bundle.get("executed_at"))
    after_time = _parse_time(after["taken_at"]) if after else None
    usable = after is not None
    if after is None:
        not_verified.append(f"Plan {plan_id}: no after snapshot given, so the new values were not checked against the model.")
    elif ran is None or after_time is None:
        usable = False
        not_verified.append(f"Plan {plan_id}: execution or capture time is missing or invalid, so the new values cannot be confirmed.")
    elif after_time < ran:
        usable = False
        not_verified.append(f"Plan {plan_id}: the after snapshot was taken before the plan ran, so it cannot confirm the new values.")
    doc = (bundle.get("document") or {}).get("doc_guid")
    if not doc or doc != _doc_guid(before) or (after is not None and doc != _doc_guid(after)):
        usable = False
        not_verified.append(f"Plan {plan_id}: its document could not be matched to the snapshot (different document or no document id).")
    checks = {"confirmed": 0, "differs": 0, "unknown": 0}
    index = {el["uid"]: el for el in after["elements"] if el.get("uid")} if usable else {}
    changes: List[Dict[str, Any]] = []
    for e in entries:
        state = "unknown"
        if usable:
            found, value = _after_value(index, e.get("uid"), e.get("parameter"))
            if found:
                state = "confirmed" if _same(value, e.get("new")) else "differs"
        checks[state] += 1
        if len(changes) < MAX_CHANGES:
            changes.append({
                "uid": _s(e.get("uid")), "element_id": e.get("element_id"), "parameter": _s(e.get("parameter")),
                "before": _s(e.get("before")) if e.get("before_recorded") else None,
                "new": _s(e.get("new")), "check": state,
            })
    if checks["differs"]:
        not_verified.append(f"Plan {plan_id}: {checks['differs']} changed value(s) differs in the after snapshot (or is in another unit).")
    if any(not e.get("before_recorded") for e in entries):
        not_verified.append(f"Plan {plan_id}: some before values were not recorded.")
    return {
        "plan_id": plan_id, "outcome": _s(bundle.get("outcome")), "approved_by": _s(bundle.get("approved_by")),
        "approver_note": _s(bundle.get("approver_note")), "approved_at": _s(bundle.get("approved_at")),
        "executed_at": _s(bundle.get("executed_at")), "changed_total": len(entries),
        "skipped": len(bundle.get("skipped") or []), "checks": checks, "changes": changes,
        "proof_verification": _s(bundle.get("verification"), 200),
    }


def _plans(plan_ids: List[str], before, after, workspace, not_verified: List[str]) -> List[Dict[str, Any]]:
    if len(plan_ids) > MAX_PLANS:
        raise ValueError(f"At most {MAX_PLANS} plan_ids per report.")
    plans: List[Dict[str, Any]] = []
    for pid in plan_ids:
        pid = proof_mod.validate_plan_id(pid)
        try:
            bundle = proof_mod.read_proof(rg._ws_dir(workspace), pid)
        except (OSError, ValueError):
            bundle = None
        if not isinstance(bundle, dict):
            not_verified.append(f"Plan {pid}: no proof bundle found (not executed, or the file is unreadable).")
            continue
        plans.append(_plan(pid, bundle, before, after, not_verified))
    return plans


def build_report_data(
    before: Dict[str, Any], after: Optional[Dict[str, Any]], rule_pack: str, plan_ids: List[str],
    max_ids: int, workspace: Any,
) -> Dict[str, Any]:
    """Pure report from loaded snapshots (rg._load_review_snapshot shape)."""
    not_verified: List[str] = [
        "Everything here comes from saved snapshots and proof bundles; nothing was re-read from the live model."
    ]
    if before["is_mock"]:
        not_verified.append("MOCK DATA: generated sample, not a real model.")
    elif not _doc_guid(before):
        not_verified.append("The snapshot has no document id, so the model identity could not be confirmed.")
    groups, failed_before = _run_rules(before, rule_pack, workspace, "Before", not_verified)
    verification = changes = None
    if after is not None:
        guid_a, guid_b = _doc_guid(before), _doc_guid(after)
        if guid_a and guid_b and guid_a != guid_b:
            raise ValueError("The two snapshots come from different Revit models, so they cannot be compared.")
        comparable = True
        if not (guid_a and guid_b):
            comparable = False
            not_verified.append("Could not confirm both snapshots are of the same model (a snapshot has no document id).")
        after_groups, failed_after = _run_rules(after, rule_pack, workspace, "After", not_verified)
        if _is_partial(before) or _is_partial(after):
            comparable = False
            not_verified.append("Whole-model re-check and change totals are unavailable because a snapshot is partial.")
        before_time, after_time = _parse_time(before["taken_at"]), _parse_time(after["taken_at"])
        if before_time is None or after_time is None or after_time < before_time:
            comparable = False
            not_verified.append("Snapshot chronology is missing, invalid or reversed; re-check and change totals are unavailable.")
        if comparable:
            verification = _verification(groups, after_groups, failed_before, failed_after, not_verified)
            changes = compare_snapshot_data(before, after, 0)["totals"]
    else:
        not_verified.append("No after snapshot given: the findings were not re-checked after any fix.")
    plans = _plans(plan_ids, before, after, workspace, not_verified)
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_source": "mock" if before["is_mock"] else "real",
        "document": {"doc_title": _s(before["source"].get("doc_title") or ""), "doc_guid": _s(_doc_guid(before))},
        "snapshot": _identity(before),
        "after_snapshot": _identity(after) if after else None,
        "rule_pack": _rule_pack_info(rule_pack, workspace),
        "findings": _findings(groups, max_ids, not_verified),
        "verification": verification,
        "changes": changes,
        "plans": plans,
        "not_verified": not_verified,
    }


def render_markdown(r: Dict[str, Any]) -> str:
    """Plain Markdown of the report, ASCII only."""
    doc, snap, pack = r["document"], r["snapshot"], r["rule_pack"]
    out = ["# QA and change report", ""]
    if r["data_source"] == "mock":
        out += ["**MOCK DATA: generated sample, not a real model.**", ""]
    out += [
        f"- Document: {doc['doc_title'] or '(no title)'} ({doc['doc_guid'] or 'no document id'})",
        f"- Snapshot: {snap['snapshot_id']}, taken {snap['taken_at'] or 'unknown'}, {snap['app']} {snap['app_version']}, "
        f"{snap['element_count']} elements",
    ]
    if r["after_snapshot"]:
        a = r["after_snapshot"]
        out.append(f"- After snapshot: {a['snapshot_id']}, taken {a['taken_at'] or 'unknown'}, {a['element_count']} elements")
    out += [f"- Rule pack: {pack['name']} ({pack['origin']}, {pack['rules']} rules, sha256 {pack['sha256'][:12]})",
            f"- Report made: {r['generated_at']}", "", "## Findings by rule", ""]
    if not r["findings"]:
        out.append("No rule findings.")
    for f in r["findings"]:
        ids = ", ".join(f["element_ids"]) + (f" (+{f['more']} more)" if f["more"] else "")
        out += [f"- [{f['severity']}] {f['rule_id']}: {f['count']} elements. {f['message']}",
                f"  Elements: {ids}", f"  Next step: {f['next_step']}"]
    v = r["verification"]
    if v:
        def known(value):
            return "unknown" if value is None else value

        out += ["", "## Re-check", "",
                f"Findings before {known(v['before_total'])}, after {known(v['after_total'])}, "
                f"resolved {known(v['resolved'])}, new {known(v['new'])}."]
        out += [f"- {x['rule_id']}: {known(x['before'])} -> {known(x['after'])}; "
                f"resolved {known(x['resolved'])}, new {known(x['new'])}" for x in v["per_rule"]]
        c = r["changes"]
        out.append(f"Between snapshots: {c['added']} added, {c['removed']} removed, {c['modified']} modified elements.")
    if r["plans"]:
        out += ["", "## Approved changes", ""]
    for p in r["plans"]:
        k = p["checks"]
        out += [f"### Plan {p['plan_id']}: {p['outcome']}",
                f"- Approved by {p['approved_by'] or 'unknown'} at {p['approved_at'] or 'unknown'} ({p['approver_note']})",
                f"- Executed {p['executed_at'] or 'unknown'}; {p['changed_total']} changed, {p['skipped']} skipped or failed",
                f"- Checked in after snapshot: {k['confirmed']} confirmed, {k['differs']} differ, {k['unknown']} not checked"]
        out += [f"  - {c['uid']} {c['parameter']}: {c['before']} -> {c['new']} ({c['check']})" for c in p["changes"]]
        if p["changed_total"] > len(p["changes"]):
            out.append(f"  - ... {p['changed_total'] - len(p['changes'])} more in the JSON file")
    out += ["", "## Not verified", ""] + [f"- {n}" for n in r["not_verified"]] + [""]
    return "\n".join(out).encode("ascii", "replace").decode("ascii")


class QaHandoverModule:
    def build_report(
        self,
        snapshot_id: str = "",
        after_snapshot_id: str = "",
        rule_pack: str = "core",
        plan_ids: Optional[List[str]] = None,
        max_ids: int = 10,
        output_name: str = "qa_handover",
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        if not _NAME_RE.fullmatch(output_name or ""):
            raise ValueError("output_name must be 1 to 64 letters, digits, '_' or '-' (no extension or path).")
        if after_snapshot_id and not snapshot_id:
            raise ValueError("after_snapshot_id needs snapshot_id as the before state.")
        before = rg._load_review_snapshot(snapshot_id, workspace)
        after = rg._load_review_snapshot(after_snapshot_id, workspace) if after_snapshot_id else None
        report = build_report_data(before, after, rule_pack, list(plan_ids or []), max(1, min(int(max_ids), MAX_IDS)), workspace)
        blob = json.dumps(report, indent=2)
        markdown = render_markdown(report)
        if max(len(blob), len(markdown)) > MAX_REPORT_BYTES:
            raise ValueError("The report is too large; lower max_ids or list fewer plan_ids.")
        paths = {}
        for ext, text in (("json", blob), ("md", markdown)):
            path = rg._confined(workspace, f"reports/{output_name}.{ext}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            paths[ext] = str(path)
        v = report["verification"]
        recheck = ""
        if after is not None:
            recheck = (f"; after snapshot {v['after_total']} findings remain" if v and v["after_total"] is not None
                       else "; re-check totals unknown or unavailable")
        return {
            "data_source": report["data_source"],
            "summary": (
                f"{sum(f['count'] for f in report['findings'])} findings in {len(report['findings'])} rules"
                + recheck
                + f"; {len(report['plans'])} plan(s); {len(report['not_verified'])} item(s) not verified."
            ),
            "json_file": paths["json"],
            "markdown_file": paths["md"],
            "not_verified_count": len(report["not_verified"]),
        }
