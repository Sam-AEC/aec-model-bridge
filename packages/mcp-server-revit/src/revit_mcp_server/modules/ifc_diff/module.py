"""
ifc_diff module - read-only GlobalId diff between two IFC files.

Command:
  compare - elements added, removed and changed between an older and a newer IFC file.
            Elements are IfcProduct instances matched by GlobalId. "Changed" means a different
            IFC class, name, or property sets and quantities. Geometry is not compared.

  compare_snapshot - a delivered IFC against a saved Revit snapshot, matched by GlobalId. Reports
            snapshot elements missing from the IFC, IFC elements missing from the snapshot, and matched
            elements, by category. Snapshot elements with no usable GUID are listed as unmatched.
            The GUID of a snapshot element is its IfcGUID parameter when the snapshot holds it (take
            the snapshot with params ["IfcGUID"]), else the one derived from the Revit UniqueId.

Both files must be .ifc files inside the workspace and no larger than MAX_IFC_BYTES. Lists are
capped; the counts are complete. A GlobalId that appears twice in one file is counted in
"duplicate_global_ids" and only its first element is compared.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from revit_mcp_server.errors import WorkspaceViolation
from revit_mcp_server.security.safe_paths import SNAPSHOT_ID_RE, safe_child
from revit_mcp_server.security.workspace import base_directory, confine_path

DEFAULT_MAX_ITEMS = 50
MAX_ITEMS = 1000
MAX_IFC_BYTES = 250_000_000
STEP_MAGIC = b"ISO-10303-21"
IFC_GUID_RE = re.compile(r"[0-9A-Za-z_$]{22}")
SRC_PARAM = "IfcGUID parameter"
SRC_UNIQUE_ID = "derived from UniqueId"


def _input_file(workspace: Any, name: Any, what: str) -> Path:
    if not isinstance(name, str) or not name.strip() or "\x00" in name:
        raise ValueError(f"{what} is required: a workspace path ending in .ifc")
    base = base_directory(workspace)
    if base is None:
        raise ValueError("A workspace is required.")
    candidate = Path(name)
    if not candidate.is_absolute():
        candidate = base / candidate
    try:
        path = confine_path(workspace, candidate)
    except WorkspaceViolation as exc:
        if getattr(workspace, "assert_in_workspace", None) is not None:
            raise
        raise ValueError(f"{what} is outside the allowed workspace directories.") from exc
    if path.suffix.lower() != ".ifc":
        raise ValueError(f"{what} must be a .ifc file.")
    if not path.is_file():
        raise ValueError(f"{what} '{name}' was not found in the workspace.")
    if path.stat().st_size > MAX_IFC_BYTES:
        raise ValueError(f"{what} is larger than {MAX_IFC_BYTES // 1_000_000} MB, which this tool does not read.")
    with open(path, "rb") as fh:
        if not fh.read(64).lstrip().startswith(STEP_MAGIC):
            raise ValueError(f"{what} is not an IFC STEP file (it does not start with ISO-10303-21).")
    return path


def _open(path: Path, what: str) -> Any:
    try:
        import ifcopenshell
    except ImportError as exc:
        raise ValueError("IFC diff needs ifcopenshell, which is not installed.") from exc
    try:
        return ifcopenshell.open(str(path))
    except Exception as exc:
        raise ValueError(f"{what} could not be read as IFC: {exc}") from exc


def _psets(element: Any) -> Dict[str, Dict[str, Any]]:
    import ifcopenshell.util.element as el_util

    try:
        raw = el_util.get_psets(element)
    except Exception:
        return {}
    return {
        pset: {k: _plain(v) for k, v in sorted(props.items()) if k != "id"}
        for pset, props in sorted(raw.items())
    }


def _plain(value: Any) -> Any:
    """A value without STEP ids, so the same data in two files compares and hashes the same.

    Entity instances become (class, GlobalId or Name or wrapped value); the step id of nested
    property dictionaries (complex properties) is dropped."""
    if hasattr(value, "is_a") and hasattr(value, "id"):
        key = (getattr(value, "GlobalId", None) or getattr(value, "Name", None)
               or getattr(value, "wrappedValue", None))
        return [value.is_a(), None if key is None else str(key)]
    if isinstance(value, dict):
        skip_id = "type" in value
        return {k: _plain(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0])) if not (skip_id and k == "id")}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _digest(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _index(model: Any, ifc_class: str) -> Tuple[Dict[str, Dict[str, Any]], int]:
    """GlobalId -> {class, name, psets, hash}; the second value counts repeated GlobalIds."""
    try:
        elements = model.by_type(ifc_class or "IfcProduct")
    except Exception as exc:
        raise ValueError(f"'{ifc_class}' is not an IFC class in this file's schema ({model.schema}).") from exc
    out: Dict[str, Dict[str, Any]] = {}
    duplicates = 0
    for el in elements:
        gid = getattr(el, "GlobalId", None)
        if not gid:
            continue
        if gid in out:
            duplicates += 1
            continue
        psets = _psets(el)
        out[gid] = {"class": el.is_a(), "name": getattr(el, "Name", None), "psets": psets, "hash": _digest(psets)}
    return out, duplicates


def _brief(gid: str, row: Dict[str, Any]) -> Dict[str, Any]:
    return {"global_id": gid, "class": row["class"], "name": row["name"]}


def _changes(old: Dict[str, Any], new: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    change: Dict[str, Any] = {}
    if old["class"] != new["class"]:
        change["class"] = {"old": old["class"], "new": new["class"]}
    if old["name"] != new["name"]:
        change["name"] = {"old": old["name"], "new": new["name"]}
    if old["hash"] != new["hash"]:
        op, np_ = old["psets"], new["psets"]
        change["property_sets"] = {
            "added": sorted(set(np_) - set(op)),
            "removed": sorted(set(op) - set(np_)),
            "changed": sorted(p for p in set(op) & set(np_) if op[p] != np_[p]),
            "old_hash": old["hash"],
            "new_hash": new["hash"],
        }
    return change or None


def _snapshot_elements(workspace: Any, snapshot_id: Any) -> List[Dict[str, Any]]:
    def refuse(_reason: str) -> Exception:
        return ValueError("snapshot_id must be a plain snapshot name inside the workspace snapshots folder.")

    base = base_directory(workspace)
    if base is None:
        raise ValueError("A workspace is required.")
    path = safe_child(base / "snapshots", snapshot_id, ".json", SNAPSHOT_ID_RE, refuse)
    if not path.is_file():
        raise ValueError(f"Snapshot '{snapshot_id}' was not found in the workspace snapshots folder.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Snapshot '{snapshot_id}' could not be read: {exc}") from exc
    elements = data.get("elements") if isinstance(data, dict) else None
    if not isinstance(elements, list):
        raise ValueError(f"Snapshot '{snapshot_id}' holds no element list.")
    return [e for e in elements if isinstance(e, dict)]


def _guid_from_param(el: Dict[str, Any]) -> Optional[str]:
    params = el.get("params")
    if not isinstance(params, dict):
        return None
    for name, val in params.items():
        if isinstance(name, str) and name.lower() in ("ifcguid", "ifc guid"):
            raw = val.get("v") if isinstance(val, dict) else val
            if isinstance(raw, str) and IFC_GUID_RE.fullmatch(raw.strip()):
                return raw.strip()
    return None


def _can_derive_guids() -> bool:
    try:
        import ifcopenshell.guid  # noqa: F401
    except ImportError:
        return False
    return True


def _guid_from_unique_id(uid: Any) -> Optional[str]:
    """Revit's IFC export GUID: the episode GUID of the UniqueId with its last four bytes XORed
    with the element id (the trailing eight hex digits). UNVERIFIED against a live export."""
    if not isinstance(uid, str):
        return None
    m = re.fullmatch(r"([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})-([0-9a-fA-F]{8})", uid)
    if not m:
        return None
    try:
        import ifcopenshell.guid
    except ImportError:
        return None
    raw = bytearray(uuid.UUID(m.group(1)).bytes)
    for i, b in enumerate(bytes.fromhex(m.group(2))):
        raw[12 + i] ^= b
    return ifcopenshell.guid.compress(bytes(raw).hex())


def _resolve_guid(el: Dict[str, Any]) -> Tuple[Optional[str], str]:
    guid = _guid_from_param(el)
    if guid:
        return guid, SRC_PARAM
    guid = _guid_from_unique_id(el.get("uid"))
    if guid:
        return guid, SRC_UNIQUE_ID
    return None, "none"


def _snap_brief(el: Dict[str, Any], guid: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
    out = {"uid": el.get("uid"), "category": el.get("category"), "name": el.get("name")}
    if guid:
        out["global_id"] = guid
    out.update(extra)
    return out


class IfcDiffModule:
    def compare(
        self,
        older_ifc_path: str = "",
        newer_ifc_path: str = "",
        ifc_class: str = "",
        max_items: int = DEFAULT_MAX_ITEMS,
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        older = _input_file(workspace, older_ifc_path, "older_ifc_path")
        newer = _input_file(workspace, newer_ifc_path, "newer_ifc_path")
        if ifc_class is not None and not isinstance(ifc_class, str):
            raise ValueError("ifc_class must be text such as IfcWall.")
        ifc_class = (ifc_class or "").strip()
        try:
            limit = max(1, min(int(max_items or DEFAULT_MAX_ITEMS), MAX_ITEMS))
        except (TypeError, ValueError):
            raise ValueError("max_items must be a whole number.") from None

        old_model = _open(older, "older_ifc_path")
        new_model = _open(newer, "newer_ifc_path")
        old_idx, old_dups = _index(old_model, ifc_class)
        new_idx, new_dups = _index(new_model, ifc_class)

        added = sorted(set(new_idx) - set(old_idx))
        removed = sorted(set(old_idx) - set(new_idx))
        changed: List[Dict[str, Any]] = []
        common = sorted(set(old_idx) & set(new_idx))
        for gid in common:
            diff = _changes(old_idx[gid], new_idx[gid])
            if diff:
                changed.append({**_brief(gid, new_idx[gid]), "changes": diff})

        notes: List[str] = ["Geometry and placement are not compared."]
        if len(added) > limit or len(removed) > limit or len(changed) > limit:
            notes.append(f"Lists are cut at {limit} elements; the counts are complete.")
        if old_dups or new_dups:
            notes.append("Some GlobalIds appear more than once in a file; only the first element of each was compared.")
        if old_model.schema != new_model.schema:
            notes.append(f"The files use different schemas ({old_model.schema} and {new_model.schema}); "
                         "class names and property sets may differ for that reason alone.")
        return {
            "read_only": True,
            "older_file": str(older),
            "newer_file": str(newer),
            "older_schema": old_model.schema,
            "newer_schema": new_model.schema,
            "ifc_class": ifc_class or "IfcProduct",
            "counts": {
                "older_elements": len(old_idx),
                "newer_elements": len(new_idx),
                "added": len(added),
                "removed": len(removed),
                "changed": len(changed),
                "unchanged": len(common) - len(changed),
            },
            "duplicate_global_ids": {"older": old_dups, "newer": new_dups},
            "added": [_brief(g, new_idx[g]) for g in added[:limit]],
            "removed": [_brief(g, old_idx[g]) for g in removed[:limit]],
            "changed": changed[:limit],
            "notes": notes,
        }

    def compare_snapshot(
        self,
        snapshot_id: str = "",
        ifc_path: str = "",
        categories: Optional[List[str]] = None,
        ifc_class: str = "",
        max_items: int = DEFAULT_MAX_ITEMS,
        workspace: Any = None,
        **_,
    ) -> Dict[str, Any]:
        ifc_file = _input_file(workspace, ifc_path, "ifc_path")
        if ifc_class is not None and not isinstance(ifc_class, str):
            raise ValueError("ifc_class must be text such as IfcWall.")
        ifc_class = (ifc_class or "").strip()
        if categories is not None and (
                not isinstance(categories, list) or not all(isinstance(c, str) for c in categories)):
            raise ValueError("categories must be a list of category names such as OST_Walls.")
        try:
            limit = max(1, min(int(max_items or DEFAULT_MAX_ITEMS), MAX_ITEMS))
        except (TypeError, ValueError):
            raise ValueError("max_items must be a whole number.") from None

        elements = _snapshot_elements(workspace, snapshot_id)
        wanted = {c.strip().lower() for c in categories or [] if c.strip()}
        if wanted:
            elements = [e for e in elements if str(e.get("category") or "").lower() in wanted]
        model = _open(ifc_file, "ifc_path")
        ifc_idx, ifc_dups = _index(model, ifc_class)

        sources = {SRC_PARAM: 0, SRC_UNIQUE_ID: 0, "none": 0}
        by_cat: Dict[str, Dict[str, int]] = {}
        matched: List[Dict[str, Any]] = []
        missing: List[Dict[str, Any]] = []
        unmatched: List[Dict[str, Any]] = []
        duplicates: List[Dict[str, Any]] = []
        seen: set = set()
        can_derive = _can_derive_guids()
        no_guid_reason = ("no IfcGUID parameter and no UniqueId to derive one from" if can_derive else
                          "no IfcGUID parameter and ifcopenshell.guid is not available to derive one from the UniqueId")

        def bucket(el: Dict[str, Any]) -> Dict[str, int]:
            return by_cat.setdefault(str(el.get("category") or "(none)"),
                                     {"matched": 0, "missing_from_ifc": 0, "unmatched_no_guid": 0,
                                      "unmatched_duplicate_guid": 0})

        for el in elements:
            guid, source = _resolve_guid(el)
            sources[source] += 1
            if guid is None:
                bucket(el)["unmatched_no_guid"] += 1
                unmatched.append(_snap_brief(el, reason=no_guid_reason))
            elif guid in seen:
                bucket(el)["unmatched_duplicate_guid"] += 1
                duplicates.append(_snap_brief(el, guid, reason="duplicate GUID", guid_source=source))
            else:
                seen.add(guid)
                if guid in ifc_idx:
                    bucket(el)["matched"] += 1
                    matched.append(_snap_brief(el, guid, ifc_class=ifc_idx[guid]["class"], guid_source=source))
                else:
                    bucket(el)["missing_from_ifc"] += 1
                    missing.append(_snap_brief(el, guid, guid_source=source))

        extra = [_brief(g, ifc_idx[g]) for g in sorted(set(ifc_idx) - seen)]
        extra_by_class: Dict[str, int] = {}
        for row in extra:
            extra_by_class[row["class"]] = extra_by_class.get(row["class"], 0) + 1

        notes: List[str] = ["Geometry and properties are not compared."]
        if sources[SRC_UNIQUE_ID]:
            notes.append("Some GUIDs were derived from the Revit UniqueId with the Revit IFC exporter rule. "
                         "UNVERIFIED against a live export; for exact matching take the snapshot with "
                         'params ["IfcGUID"].')
        if not can_derive and any(
                _guid_from_param(e) is None and isinstance(e.get("uid"), str) for e in elements):
            notes.append("ifcopenshell.guid is not available, so GUIDs could not be derived from the UniqueId. "
                         "Elements without an IfcGUID parameter are listed in unmatched_no_guid for that reason; "
                         "install ifcopenshell or take the snapshot with params [\"IfcGUID\"].")
        if elements and sources[SRC_PARAM] == 0:
            notes.append("The snapshot holds no IfcGUID parameter, so no element was matched on it. Take the "
                         'snapshot with params ["IfcGUID"] to match on the GUID Revit stored.')
        if wanted or ifc_class:
            notes.append("Filters narrow one side only: categories the snapshot, ifc_class the IFC file. "
                         "Elements outside the other side's filter can show as missing or extra.")
        if ifc_dups:
            notes.append("Some GlobalIds appear more than once in the IFC file; only the first element of each was used.")
        if duplicates:
            notes.append("Elements whose GUID repeats an earlier snapshot element are counted in "
                         "unmatched_duplicate_guid, not in unmatched_no_guid.")
        if any(len(x) > limit for x in (matched, missing, extra, unmatched, duplicates)):
            notes.append(f"Lists are cut at {limit} elements; the counts are complete.")
        return {
            "read_only": True,
            "snapshot_id": snapshot_id,
            "ifc_file": str(ifc_file),
            "ifc_schema": model.schema,
            "ifc_class": ifc_class or "IfcProduct",
            "counts": {
                "snapshot_elements": len(elements),
                "ifc_elements": len(ifc_idx),
                "matched": len(matched),
                "missing_from_ifc": len(missing),
                "extra_in_ifc": len(extra),
                "unmatched_no_guid": len(unmatched),
                "unmatched_duplicate_guid": len(duplicates),
            },
            "guid_sources": sources,
            "by_category": by_cat,
            "extra_by_ifc_class": extra_by_class,
            "duplicate_global_ids_in_ifc": ifc_dups,
            "matched": matched[:limit],
            "missing_from_ifc": missing[:limit],
            "extra_in_ifc": extra[:limit],
            "unmatched_no_guid": unmatched[:limit],
            "unmatched_duplicate_guid": duplicates[:limit],
            "notes": notes,
        }
