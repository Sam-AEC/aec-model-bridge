"""
clash_triage module - read-only triage of Navisworks clash results (see docs/clash-triage.md, slice A).

Commands:
  match_clashes     - Match both items of every clash to Revit elements and report how sure each match is.
  list_clash_issues - List the clash issues recorded earlier.

Rules (see docs/clash-triage.md):
  - The only keys used to find a Revit element are its UniqueId and its IFC GUID
    parameter. Revit ElementId and the Navisworks InstanceGuid are never used.
  - Every item gets a confidence: exact (one element found), ambiguous (more than
    one element found, none is chosen) or unmatched (nothing found). No guessing.
  - Nothing here changes the Revit model. Results are saved in the workspace file
    ``clash_triage.db``, a separate store from the QA/QC rule issues so a QA/QC
    re-run cannot auto-resolve them.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_FILENAME = "clash_triage.db"
RULE_ID = "clash_triage"
_RANK = {"exact": 0, "ambiguous": 1, "unmatched": 2}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn(workspace: Any) -> sqlite3.Connection:
    conn = sqlite3.connect(str(workspace.allowed_directories[0] / DB_FILENAME))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS clash_issues (
            id TEXT PRIMARY KEY,
            doc_guid TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            clash_guid TEXT NOT NULL,
            clash_name TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            match TEXT NOT NULL,
            element_uid_a TEXT,
            element_uid_b TEXT,
            match_kind_a TEXT,
            match_kind_b TEXT,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _norm_param_name(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _ifc_guid_of(el: Dict[str, Any]) -> Optional[str]:
    for pname, pval in (el.get("params") or {}).items():
        if _norm_param_name(pname) in ("ifcguid", "ifcglobalid"):
            v = pval.get("v") if isinstance(pval, dict) else pval
            if v not in (None, ""):
                return str(v)
    return None


def _build_index(elements: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_uid: Dict[str, List[Dict[str, Any]]] = {}
    by_ifc: Dict[str, List[Dict[str, Any]]] = {}
    for el in elements:
        uid = el.get("uid")
        if uid:
            by_uid.setdefault(str(uid).lower(), []).append(el)
        ifc = _ifc_guid_of(el)
        if ifc:
            by_ifc.setdefault(ifc, []).append(el)  # IFC GUIDs are case-sensitive
    return {"uid": by_uid, "ifc": by_ifc}


def _describe(el: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "uid": el.get("uid"),
        "category": el.get("category"),
        "family": el.get("family"),
        "type_name": el.get("type_name"),
        "level_uid": el.get("level_uid"),
    }


def _match_item(item: Any, index: Dict[str, Any]) -> Dict[str, Any]:
    """Match one Navisworks item identity to Revit elements. Never guesses."""
    if not isinstance(item, dict):
        return {"item_name": None, "ifc_guid": None, "confidence": "unmatched", "match_kind": None,
                "element": None, "candidates": [], "reason": "The clash has no item on this side."}

    guid = item.get("ifcGuid") or item.get("ifc_guid")
    base = {"item_name": item.get("displayName"), "ifc_guid": guid}
    if not guid:
        return {**base, "confidence": "unmatched", "match_kind": None, "element": None,
                "candidates": [],
                "reason": "Navisworks gave no GUID for this item, so it cannot be matched safely."}

    guid = str(guid).strip()
    found: Dict[str, Dict[str, Any]] = {}
    kinds: Dict[str, str] = {}
    for el in index["uid"].get(guid.lower(), []):
        key = str(id(el))
        found[key] = el
        kinds[key] = "unique_id"
    for el in index["ifc"].get(guid, []):
        key = str(id(el))
        if key not in found:
            found[key] = el
            kinds[key] = "ifc_guid"

    if len(found) == 1:
        key = next(iter(found))
        return {**base, "confidence": "exact", "match_kind": kinds[key],
                "element": _describe(found[key]), "candidates": [], "reason": None}
    if len(found) > 1:
        return {**base, "confidence": "ambiguous", "match_kind": None, "element": None,
                "candidates": [_describe(e) for e in found.values()],
                "reason": f"{len(found)} Revit elements share this GUID; none was chosen."}
    return {**base, "confidence": "unmatched", "match_kind": None, "element": None,
            "candidates": [],
            "reason": "No Revit element in the snapshot has this UniqueId or IFC GUID "
                      "(the model may have changed since the clash test was run)."}


def _extract_results(clash_results: Any) -> List[Dict[str, Any]]:
    if isinstance(clash_results, str):
        try:
            clash_results = json.loads(clash_results)
        except ValueError as e:
            raise ValueError(f"clash_results is not valid JSON: {e}") from e
    if isinstance(clash_results, dict):
        if isinstance(clash_results.get("results"), list):
            return clash_results["results"]
        inner = clash_results.get("result")
        if isinstance(inner, dict) and isinstance(inner.get("results"), list):
            return inner["results"]
        if clash_results.get("mock"):
            return []
        raise ValueError("clash_results has no 'results' list. Pass the output of navisworks_get_clash_results.")
    if isinstance(clash_results, list):
        return clash_results
    raise ValueError("clash_results must be the output of navisworks_get_clash_results or its list of results.")


def _overall(a: str, b: str) -> str:
    return a if _RANK[a] >= _RANK[b] else b


def _bcf(*names: str) -> tuple:
    """Hardened XML/zip readers from bcf_exchange, loaded by path (the registry owns its module name)."""
    mod = sys.modules.get("_amb_bcf_exchange_impl")
    if mod is None:
        spec = importlib.util.spec_from_file_location("_amb_bcf_exchange_impl", Path(__file__).resolve().parent.parent / "bcf_exchange" / "module.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.modules["_amb_bcf_exchange_impl"] = mod
    return tuple(getattr(mod, n) for n in names)


_GUID_NAMES = {"ifcguid", "ifcglobalid", "guid", "itemguid", "uniqueid"}
_MAX_REPORT_BYTES = 50 * 1024 * 1024


def _named_values(obj: Any) -> Dict[str, str]:
    """Navisworks objectattribute/smarttag name -> value (normalised names)."""
    _child_text, _local = _bcf('_child_text', '_local')

    out: Dict[str, str] = {}
    for el in obj.iter():
        if _local(el.tag) in ("objectattribute", "smarttag"):
            name, value = _child_text(el, "name"), _child_text(el, "value")
            if name and value:
                out.setdefault(_norm_param_name(name), value)
    return out


def _navisworks_item(obj: Any) -> Dict[str, Any]:
    _child_text, = _bcf('_child_text')

    values = _named_values(obj)
    guid = next((values[k] for k in ("ifcguid", "ifcglobalid", "uniqueid", "guid", "itemguid") if k in values), None)
    item: Dict[str, Any] = {"displayName": values.get("itemname") or values.get("name"),
                            "ifcGuid": guid, "level": _child_text(obj, "layer") or None}
    if not guid and values.get("elementid"):
        item["element_id"] = values["elementid"]
    return item


def _read_navisworks_xml(path: Path) -> List[Dict[str, Any]]:
    _local, _safe_xml = _bcf('_local', '_safe_xml')

    root = _safe_xml(path.read_bytes(), path.name)
    results = []
    for res in root.iter():
        if _local(res.tag) != "clashresult":
            continue
        objs = [o for o in res.iter() if _local(o.tag) == "clashobject"]
        items = [_navisworks_item(o) for o in objs[:2]]
        results.append({"guid": res.attrib.get("guid"), "displayName": res.attrib.get("name"),
                        "status": res.attrib.get("status"), "distance": res.attrib.get("distance"),
                        "item1": items[0] if items else None, "item2": items[1] if len(items) > 1 else None})
    if not results:
        raise ValueError(f"'{path.name}' has no clash results (no <clashresult> elements).")
    return results


def _read_bcf_clashes(path: Path) -> List[Dict[str, Any]]:
    _read_bcf, = _bcf('_read_bcf')

    results = []
    for topic in _read_bcf(path)["issues"]:
        guids = topic["ifc_guids"] or topic["element_uids"]
        items = [{"displayName": None, "ifcGuid": g} for g in guids[:2]]
        results.append({"guid": topic["id"], "displayName": topic["title"], "status": topic["status"],
                        "distance": None, "item1": items[0] if items else None,
                        "item2": items[1] if len(items) > 1 else None})
    if not results:
        raise ValueError(f"'{path.name}' has no BCF topics.")
    return results


def _side_key(side: Dict[str, Any]) -> str:
    el = side.get("element")
    return el["uid"] if el else "unmatched:" + str(side.get("item_name") or side.get("ifc_guid") or "?")


class ClashTriageModule:

    def match_clashes(
        self,
        clash_results: Any = None,
        snapshot_id: str = "",
        record_issues: bool = True,
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        if clash_results is None:
            raise ValueError("clash_results is required.")
        results = _extract_results(clash_results)
        elements, doc_guid = self._get_data(snapshot_id, workspace)
        index = _build_index(elements)

        clashes = []
        for i, res in enumerate(results):
            res = res if isinstance(res, dict) else {}
            a = _match_item(res.get("item1"), index)
            b = _match_item(res.get("item2"), index)
            overall = _overall(a["confidence"], b["confidence"])
            clashes.append({
                "clash_guid": res.get("guid") or f"clash-{i}",
                "clash_name": res.get("displayName"),
                "navisworks_status": res.get("status"),
                "distance": res.get("distance"),
                "confidence": overall,
                "item1": a,
                "item2": b,
                "note": self._note(overall),
            })

        summary = {k: sum(1 for c in clashes if c["confidence"] == k) for k in _RANK}
        recorded = 0
        if record_issues and workspace is not None and clashes:
            recorded = self._record(workspace, doc_guid, clashes)

        return {
            "read_only": True,
            "doc_guid": doc_guid,
            "total_clashes": len(clashes),
            "summary": summary,
            "issues_recorded": recorded,
            "clashes": clashes,
            "unverified": "Matching was tested on fixtures only. What Navisworks puts in the GUID field "
                          "for Revit, IFC or NWC sources has not been checked on a live project.",
        }

    def import_clash_report(
        self,
        report_path: str = "",
        snapshot_id: str = "",
        record_issues: bool = True,
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        _resolve_in_workspace, = _bcf('_resolve_in_workspace')

        path = _resolve_in_workspace(report_path, workspace)
        suffix = path.suffix.lower()
        if suffix not in (".xml", ".bcfzip", ".bcf"):
            raise ValueError("report_path must be a Navisworks clash report or BCF file: .xml or .bcfzip.")
        if not path.is_file():
            raise ValueError(f"File '{report_path}' not found in the workspace.")
        if path.stat().st_size > _MAX_REPORT_BYTES:
            raise ValueError(f"'{path.name}' is larger than {_MAX_REPORT_BYTES // (1024 * 1024)} MB.")
        if suffix == ".xml":
            fmt, results = "navisworks_xml", _read_navisworks_xml(path)
        else:
            fmt, results = "bcf", _read_bcf_clashes(path)

        out = self.match_clashes(clash_results=results, snapshot_id=snapshot_id,
                                 record_issues=record_issues, workspace=workspace)
        groups: Dict[tuple, Dict[str, Any]] = {}
        unmatched = []
        for res, clash in zip(results, out["clashes"]):
            sides = [clash["item1"], clash["item2"]]
            level = next((i.get("level") for i in (res.get("item1"), res.get("item2")) if isinstance(i, dict)
                          and i.get("level")), None)
            if level is None:
                level = next((s["element"].get("level_uid") for s in sides if s.get("element")), None)
            key = (tuple(sorted(_side_key(s) for s in sides)), level)
            group = groups.setdefault(key, {"level": level, "element_uids": [k for k in key[0]
                                            if not k.startswith("unmatched:")],
                                            "confidence": "exact", "clash_count": 0, "clash_guids": []})
            group["clash_count"] += 1
            group["clash_guids"].append(clash["clash_guid"])
            group["confidence"] = _overall(group["confidence"], clash["confidence"])
            if clash["confidence"] == "unmatched":
                reasons = []
                for raw, side in zip((res.get("item1"), res.get("item2")), sides):
                    if side["confidence"] != "unmatched":
                        continue
                    if isinstance(raw, dict) and raw.get("element_id"):
                        reasons.append(f"Only a Revit Element ID ({raw['element_id']}) was given; Element IDs are "
                                       "not matched because they may come from a linked model.")
                    else:
                        reasons.append(side["reason"])
                unmatched.append({"clash_guid": clash["clash_guid"], "clash_name": clash["clash_name"],
                                  "reason": " ".join(reasons)})
        out.update({
            "format": fmt,
            "report_path": str(path),
            "groups": sorted(groups.values(), key=lambda g: (-g["clash_count"], str(g["level"]))),
            "unmatched": unmatched,
            "fix_plans": [],
            "fix_plan_note": "No fix rule applies to these clash groups, so no plan was drafted. Any fix must go "
                             "through plan_actions and a person's approval before execute_plan.",
        })
        return out

    def list_clash_issues(
        self,
        doc_guid: str = "",
        status: Optional[str] = None,
        match: Optional[str] = None,
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        db_path = Path(workspace.allowed_directories[0]) / DB_FILENAME
        if not db_path.exists():
            # Listing must not create the store.
            return {"total": 0, "issues": []}
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        query, params = "SELECT * FROM clash_issues WHERE 1=1", []
        for col, val in (("doc_guid", doc_guid), ("status", status), ("match", match)):
            if val:
                query += f" AND {col}=?"
                params.append(val)
        try:
            rows = [dict(r) for r in conn.execute(query + " ORDER BY created_at", params)]
        except sqlite3.OperationalError:  # store exists but has no table yet
            rows = []
        finally:
            conn.close()
        return {"total": len(rows), "issues": rows}

    # ------------------------------------------------------------------

    @staticmethod
    def _note(overall: str) -> str:
        return {
            "exact": "Both items matched one Revit element each. Check them in Revit before acting.",
            "ambiguous": "At least one item matched several Revit elements. Decide by hand.",
            "unmatched": "At least one item could not be found in the snapshot. No fix should be proposed.",
        }[overall]

    def _record(self, workspace: Any, doc_guid: str, clashes: List[Dict[str, Any]]) -> int:
        conn = _conn(workspace)
        now = _now()
        for c in clashes:
            a, b = c["item1"], c["item2"]
            uid_a = (a["element"] or {}).get("uid")
            uid_b = (b["element"] or {}).get("uid")
            severity = "info" if c["confidence"] == "exact" else "warning"
            message = (
                f"Clash '{c['clash_name'] or c['clash_guid']}': {c['confidence']} match. "
                f"{a['item_name']} -> {uid_a or a['confidence']}; {b['item_name']} -> {uid_b or b['confidence']}."
            )
            existing = conn.execute(
                "SELECT id FROM clash_issues WHERE doc_guid=? AND clash_guid=? AND status='open'",
                (doc_guid, c["clash_guid"]),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE clash_issues SET match=?, severity=?, clash_name=?, element_uid_a=?, element_uid_b=?, "
                    "match_kind_a=?, match_kind_b=?, message=?, updated_at=? WHERE id=?",
                    (c["confidence"], severity, c["clash_name"], uid_a, uid_b,
                     a["match_kind"], b["match_kind"], message, now, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO clash_issues (id, doc_guid, rule_id, severity, clash_guid, clash_name, status, "
                    "match, element_uid_a, element_uid_b, match_kind_a, match_kind_b, message, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?, 'open', ?,?,?,?,?,?,?,?)",
                    (str(uuid.uuid4()), doc_guid, RULE_ID, severity, c["clash_guid"], c["clash_name"],
                     c["confidence"], uid_a, uid_b, a["match_kind"], b["match_kind"], message, now, now),
                )
        conn.commit()
        conn.close()
        return len(clashes)

    def _get_data(self, snapshot_id: str, workspace: Any):
        if not snapshot_id:
            from revit_mcp_server.semantic.engine import generate_mock_snapshot, require_snapshot_or_mock
            require_snapshot_or_mock(snapshot_id, "clash_triage")
            snap = generate_mock_snapshot()
            return [el.model_dump(by_alias=True) for el in snap.elements], "mock-doc"
        from revit_mcp_server.security.safe_paths import snapshot_file

        snap_path = snapshot_file(Path(workspace.allowed_directories[0]) / "snapshots", snapshot_id)
        if not snap_path.exists():
            raise ValueError(f"Snapshot '{snapshot_id}' not found.")
        with open(snap_path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("elements", []), data.get("source", {}).get("doc_guid", snapshot_id)
