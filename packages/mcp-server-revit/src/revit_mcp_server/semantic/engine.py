from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from revit_mcp_server.semantic.models import (
    ElementRecord,
    RelationRecord,
    TypeRecord,
    SourceMetadata,
    Snapshot,
    BBox,
    LocationPoint,
    ParamVal,
)

logger = logging.getLogger(__name__)


def require_snapshot_or_mock(snapshot_id: str, tool: str) -> None:
    """Refuse to fall back to generated mock data unless mock mode is explicit.

    Callers invoke this when ``snapshot_id`` is empty. In bridge (live) mode an
    omitted snapshot must not be answered with synthetic data that looks like
    findings about the open model.
    """
    from revit_mcp_server.config import BridgeMode, config

    if config.mode != BridgeMode.mock:
        raise ValueError(
            f"{tool} requires a snapshot_id when connected to Revit (mode='{config.mode.value}'). "
            "Capture one first with the snapshot tool and pass its snapshot_id; "
            "generated mock data is only used when MCP_REVIT_MODE=mock."
        )


def generate_mock_snapshot() -> Snapshot:
    snapshot_id = f"01J{uuid.uuid4().hex[:23].upper()}"
    taken_at = datetime.now(timezone.utc)
    
    # Create levels
    level1_uid = "c0326e0e-473d-4952-b8ec-f23696541f41-level-1"
    level2_uid = "c0326e0e-473d-4952-b8ec-f23696541f42-level-2"
    wall_uid = "c0326e0e-473d-4952-b8ec-f23696541f43-wall-1"
    door_uid = "c0326e0e-473d-4952-b8ec-f23696541f44-door-1"
    room_unplaced_uid = "c0326e0e-473d-4952-b8ec-f23696541f45-room-unplaced"
    room_placed_uid = "c0326e0e-473d-4952-b8ec-f23696541f46-room-placed"
    
    elements = [
        # Level 1
        ElementRecord(
            uid=level1_uid,
            element_id=100,
            category="OST_Levels",
            cls="Level",
            type_name="Level 1",
            params={
                "Elevation": ParamVal(v=0.0, storage="Double", instance=True, readonly=True)
            }
        ),
        # Level 2
        ElementRecord(
            uid=level2_uid,
            element_id=101,
            category="OST_Levels",
            cls="Level",
            type_name="Level 2",
            params={
                "Elevation": ParamVal(v=4.0, storage="Double", instance=True, readonly=True)
            }
        ),
        # A Wall
        ElementRecord(
            uid=wall_uid,
            element_id=200,
            category="OST_Walls",
            cls="Wall",
            type_uid="wall-type-uid-0001",
            family="Basic Wall",
            type_name="Generic - 200mm",
            level_uid=level1_uid,
            params={
                "Unconnected Height": ParamVal(v=4.0, storage="Double", instance=True),
                "Length": ParamVal(v=10.0, storage="Double", instance=True, readonly=True)
            },
            bbox=BBox(min=[0.0, 0.0, 0.0], max=[10.0, 0.2, 4.0])
        ),
        # A Placed Door in the Wall
        ElementRecord(
            uid=door_uid,
            element_id=300,
            category="OST_Doors",
            cls="FamilyInstance",
            type_uid="door-type-uid-0001",
            family="Single-Flush",
            type_name="0915 x 2134mm",
            level_uid=level1_uid,
            host_uid=wall_uid,
            params={
                "Mark": ParamVal(v="D-101", storage="String", instance=True),
                "FireRating": ParamVal(v="30", storage="String", instance=True)
            },
            location=LocationPoint(xyz=[5.0, 0.0, 0.0], rotation=0.0),
            bbox=BBox(min=[4.5, -0.1, 0.0], max=[5.5, 0.1, 2.1])
        ),
        # An Unplaced Room (OST_Rooms)
        ElementRecord(
            uid=room_unplaced_uid,
            element_id=400,
            category="OST_Rooms",
            cls="Room",
            type_name="Office 1",
            params={
                "Number": ParamVal(v="101", storage="String", instance=True),
                "Area": ParamVal(v=0.0, storage="Double", instance=True, readonly=True)
            }
        ),
        # A Placed Room (OST_Rooms)
        ElementRecord(
            uid=room_placed_uid,
            element_id=401,
            category="OST_Rooms",
            cls="Room",
            type_name="Kitchen",
            level_uid=level1_uid,
            params={
                "Number": ParamVal(v="102", storage="String", instance=True),
                "Area": ParamVal(v=15.5, storage="Double", instance=True, readonly=True)
            },
            location=LocationPoint(xyz=[2.0, 2.0, 0.0])
        )
    ]
    
    relations = [
        RelationRecord(kind="hosts", **{"from": wall_uid, "to": door_uid}),
        RelationRecord(kind="on_level", **{"from": door_uid, "to": level1_uid}),
        RelationRecord(kind="on_level", **{"from": wall_uid, "to": level1_uid}),
        RelationRecord(kind="on_level", **{"from": room_placed_uid, "to": level1_uid})
    ]
    
    types = [
        TypeRecord(
            uid="wall-type-uid-0001",
            category="OST_Walls",
            family="Basic Wall",
            type_name="Generic - 200mm",
            family_source="system"
        ),
        TypeRecord(
            uid="door-type-uid-0001",
            category="OST_Doors",
            family="Single-Flush",
            type_name="0915 x 2134mm",
            family_source="loadable"
        )
    ]
    
    counts = {
        "by_category": {
            "OST_Levels": 2,
            "OST_Walls": 1,
            "OST_Doors": 1,
            "OST_Rooms": 2
        }
    }
    
    return Snapshot(
        schema="amb.snapshot/1",
        snapshot_id=snapshot_id,
        taken_at=taken_at,
        source=SourceMetadata(
            doc_title="Mock_Project.rvt",
            doc_guid="mock-doc-guid-12345",
            units="SI",
            phase_map={"4": "New Construction"}
        ),
        elements=elements,
        relations=relations,
        types=types,
        counts=counts
    )

def _store_snapshot_file(workspace: Any, snapshot_id: str, source_path: Any) -> None:
    """Make sure ``snapshots/{snapshot_id}.json`` exists in the Python workspace.

    The add-in writes under its own workspace environment, which can differ from
    this process's; copy the file across when they do.
    """
    import shutil
    from pathlib import Path

    from revit_mcp_server.security.safe_paths import snapshot_file

    snapshots_dir = workspace.allowed_directories[0] / "snapshots"
    target = snapshot_file(snapshots_dir, snapshot_id)  # refuse a hostile id before touching the disk
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    if source_path and Path(source_path).resolve() != target.resolve() and not target.exists():
        shutil.copyfile(source_path, target)


# --- Snapshot options, slices and incremental merge (issues 289, 290) -------------------------------

SNAPSHOT_MAX_PARAMS = 100
SNAPSHOT_MAX_PARAM_NAME = 200
SLICE_SIZE_MIN = 10
SLICE_SIZE_MAX = 5000
# A sliced capture stops after this much wall time or this many slices and is then marked truncated.
SLICED_MAX_TOTAL_SECONDS = 600.0
SLICED_MAX_SLICES = 2000

_PART_FILE_RE = re.compile(r"(?P<sid>[A-Za-z0-9_-]{1,64})\.(?:part-(?:start|\d{7})|delta)\.json")


class IncrementalMergeError(ValueError):
    """The incremental capture cannot be merged with its base; a full capture is needed."""


def validate_snapshot_params(value: Any) -> Optional[List[str]]:
    """The optional ``params`` list: names of the parameters to read. None when absent; ValueError when malformed."""
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("params must be a list of parameter names, for example [\"Mark\", \"Fire Rating\"].")
    names: List[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("params must contain only parameter names (strings).")
        name = item.strip()
        if not name:
            raise ValueError("params must not contain an empty name.")
        if len(name) > SNAPSHOT_MAX_PARAM_NAME:
            raise ValueError(f"params names must be at most {SNAPSHOT_MAX_PARAM_NAME} characters.")
        if name not in names:
            names.append(name)
    if not names:
        raise ValueError("params must name at least one parameter; leave it out to read every parameter.")
    if len(names) > SNAPSHOT_MAX_PARAMS:
        raise ValueError(f"params can name at most {SNAPSHOT_MAX_PARAMS} parameters.")
    return names


def validate_slice_size(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("slice_size must be a whole number of elements per slice.")
    if not SLICE_SIZE_MIN <= value <= SLICE_SIZE_MAX:
        raise ValueError(f"slice_size must be between {SLICE_SIZE_MIN} and {SLICE_SIZE_MAX}.")
    return value


def _snapshot_payload(options: Dict[str, Any]) -> Dict[str, Any]:
    """The add-in payload for snapshot_take options, validated. Unknown keys are dropped."""
    payload: Dict[str, Any] = {}
    for key in ("categories", "max_elements", "time_budget_ms"):
        if options.get(key) is not None:
            payload[key] = options[key]
    params = validate_snapshot_params(options.get("params"))
    if params is not None:
        payload["params"] = params
    slice_size = validate_slice_size(options.get("slice_size"))
    if slice_size is not None:
        payload["slice_size"] = slice_size
    return payload


def _category_key(name: Any) -> str:
    text = str(name).strip().lower()
    return text[4:] if text.startswith("ost_") else text


def incremental_base_problem(base: Dict[str, Any], payload: Dict[str, Any]) -> Optional[str]:
    """Why ``base`` cannot serve as the base of an incremental capture with ``payload``; None when it can."""
    counts = base.get("counts") if isinstance(base.get("counts"), dict) else {}
    if base.get("schema") != "amb.snapshot/1":
        return "The base snapshot has an unknown schema."
    if counts.get("truncated"):
        return "The base snapshot is a partial capture (truncated)."
    if base.get("dirty_only") or counts.get("dirty_only"):
        return "The base snapshot is a dirty-only capture."
    tracker = counts.get("tracker")
    if (not isinstance(tracker, dict) or not isinstance(tracker.get("epoch"), str) or not tracker.get("epoch")
            or isinstance(tracker.get("seq"), bool) or not isinstance(tracker.get("seq"), int)):
        return "The base snapshot has no change-journal position (taken in mock mode or by an older add-in)."
    base_cats = {_category_key(c) for c in counts.get("categories") or []}
    want_cats = {_category_key(c) for c in payload.get("categories") or []}
    if base_cats != want_cats:
        return "The base snapshot covers different categories."
    if set(counts.get("params") or []) != set(payload.get("params") or []):
        return "The base snapshot read a different params list."
    return None


def merge_incremental(base: Dict[str, Any], delta: Dict[str, Any], base_snapshot_id: str) -> Dict[str, Any]:
    """A full snapshot from ``base`` plus an incremental capture ``delta``.

    ``delta`` holds the re-read records and ``current_uids``: every UniqueId in scope now, in the order
    a full capture writes them. Records come from the delta when re-read, else from the base. Base
    records missing from ``current_uids`` were deleted. Raises IncrementalMergeError when the two do
    not fit together, so the caller takes a full snapshot instead of guessing.
    """
    current = delta.get("current_uids")
    if not isinstance(current, list) or not all(isinstance(u, str) and u for u in current):
        raise IncrementalMergeError("the incremental capture has no list of current elements")
    if len(set(current)) != len(current):
        raise IncrementalMergeError("the list of current elements repeats an element")
    delta_counts = delta.get("counts") if isinstance(delta.get("counts"), dict) else {}
    if delta_counts.get("truncated"):
        raise IncrementalMergeError("the incremental capture was cut short by its time or element limit")
    base_guid = (base.get("source") or {}).get("doc_guid")
    delta_guid = (delta.get("source") or {}).get("doc_guid")
    if base_guid and delta_guid and base_guid != delta_guid:
        raise IncrementalMergeError("the base snapshot is of another document")

    changed: Dict[str, Any] = {}
    for el in delta.get("elements") or []:
        uid = el.get("uid") if isinstance(el, dict) else None
        if not uid:
            raise IncrementalMergeError("a re-read element has no uid")
        changed[uid] = el
    current_set = set(current)
    stray = [uid for uid in changed if uid not in current_set]
    if stray:
        raise IncrementalMergeError(f"{len(stray)} re-read element(s) are not in the current element list")
    base_map: Dict[str, Any] = {}
    for el in base.get("elements") or []:
        if isinstance(el, dict) and el.get("uid"):
            base_map[el["uid"]] = el

    merged: List[Any] = []
    for uid in current:
        if uid in changed:
            merged.append(changed[uid])
        elif uid in base_map:
            merged.append(base_map[uid])
        else:
            raise IncrementalMergeError(
                f"element {uid} is in the model but neither in the base snapshot nor among the changed elements")

    added = sum(1 for uid in changed if uid not in base_map)
    deleted = [uid for uid in base_map if uid not in current_set]
    data = {k: v for k, v in delta.items() if k not in ("current_uids", "incremental")}
    data["elements"] = merged
    counts = dict(delta_counts)
    counts.update({
        "candidates": len(current),
        "captured": len(merged),
        "truncated": False,
        "incremental": True,
        "base_snapshot_id": base_snapshot_id,
        "incremental_changes": {
            "reread": len(changed),
            "added": added,
            "modified": len(changed) - added,
            "deleted": len(deleted),
        },
    })
    counts.pop("incremental_reason", None)
    data["counts"] = counts
    return data


def assemble_slices(parts: List[Dict[str, Any]], *, stopped_early: bool = False,
                    changed_during_capture: bool = False, elapsed_ms: Optional[int] = None) -> Dict[str, Any]:
    """One snapshot from the part files of a sliced capture, in the order they were read."""
    if not parts:
        raise ValueError("a sliced snapshot needs at least one part")
    first = parts[0]
    data = {k: v for k, v in first.items() if k != "part"}
    data["elements"] = [el for part in parts for el in (part.get("elements") or [])]
    counts = dict(first.get("counts") or {})
    last_counts = parts[-1].get("counts") or {}
    if "skipped_area_volume_values" in last_counts:
        counts["skipped_area_volume_values"] = last_counts["skipped_area_volume_values"]
    views_in_scope = counts.pop("views_in_scope", False)
    if not views_in_scope:
        data["views"] = None
        data["sheets"] = None
    counts["captured"] = len(data["elements"])
    counts["truncated"] = bool(counts.get("truncated")) or stopped_early
    counts["sliced"] = True
    counts["slices"] = len(parts)
    counts["changed_during_capture"] = changed_during_capture
    if elapsed_ms is not None:
        counts["elapsed_ms"] = elapsed_ms
    data["counts"] = counts
    return data


def project_snapshot_params(snapshot: Snapshot, names: List[str]) -> None:
    """Keep only the named parameters on every element (mock mode; the add-in projects at read time)."""
    wanted = set(names)
    for el in snapshot.elements:
        el.params = {k: v for k, v in el.params.items() if k in wanted}
    snapshot.counts["params"] = list(names)


def _read_json_file(path: Any) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise RuntimeError("the snapshot file does not hold a JSON object")
    return data


def _discard_part_file(path: Any, snapshot_id: str) -> None:
    """Remove a slice or delta file the add-in wrote, once its content is merged. Only files named like one."""
    try:
        p = Path(str(path))
        match = _PART_FILE_RE.fullmatch(p.name)
        if match and match.group("sid") == snapshot_id and p.parent.name == "snapshots" and p.is_file():
            p.unlink()
    except OSError as e:
        logger.warning(f"Could not remove snapshot part file {path}: {e}")


def _save_snapshot_data(workspace: Any, data: Dict[str, Any]) -> Snapshot:
    """Validate ``data`` and write it to ``snapshots/{snapshot_id}.json`` in the Python workspace."""
    from revit_mcp_server.security.safe_paths import snapshot_file

    snapshot = Snapshot(**data)
    snapshots_dir = workspace.allowed_directories[0] / "snapshots"
    target = snapshot_file(snapshots_dir, snapshot.snapshot_id)
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return snapshot


def _load_snapshot_data(workspace: Any, snapshot_id: Any) -> Dict[str, Any]:
    from revit_mcp_server.security.safe_paths import snapshot_file

    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ValueError("base_snapshot_id must be the snapshot_id of a saved snapshot.")
    path = snapshot_file(workspace.allowed_directories[0] / "snapshots", snapshot_id)
    if not path.exists():
        raise ValueError(f"Base snapshot '{snapshot_id}' not found in the workspace snapshots folder.")
    try:
        return _read_json_file(path)
    except (OSError, ValueError, RuntimeError) as e:
        raise ValueError(f"Base snapshot '{snapshot_id}' could not be read: {e}") from e


async def _collect_slices(provider: Any, first: Dict[str, Any]) -> Dict[str, Any]:
    """Ask for the remaining slices of a sliced capture and assemble them into one snapshot."""
    snapshot_id = first.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise RuntimeError("the first slice has no snapshot_id")
    started = time.monotonic()
    parts: List[Dict[str, Any]] = []
    paths: List[Any] = []
    changed = False
    stopped_early = True
    expected_offset = 0
    res = first
    for _ in range(SLICED_MAX_SLICES):
        if not isinstance(res, dict) or res.get("sliced") is not True:
            raise RuntimeError(
                "a snapshot slice did not come back as a slice (the slice may have outlived the request wait); "
                "take the snapshot again, with a smaller slice_size")
        if res.get("snapshot_id") != snapshot_id or not res.get("path"):
            raise RuntimeError("a snapshot slice belongs to another snapshot or has no file")
        part = _read_json_file(res["path"])
        info = part.get("part") if isinstance(part.get("part"), dict) else {}
        offset, next_offset = info.get("offset"), info.get("next_offset")
        if part.get("snapshot_id") != snapshot_id or offset != expected_offset or not isinstance(next_offset, int):
            raise RuntimeError("snapshot slices arrived out of order")
        if next_offset <= offset and not (info.get("first") and not part.get("elements")):
            raise RuntimeError("a snapshot slice made no progress")
        parts.append(part)
        paths.append(res["path"])
        changed = changed or bool(res.get("changed_during_capture"))
        cursor = res.get("next_cursor")
        if not cursor:
            stopped_early = False
            break
        if not isinstance(cursor, str):
            raise RuntimeError("a snapshot slice returned an invalid cursor")
        expected_offset = next_offset
        if time.monotonic() - started > SLICED_MAX_TOTAL_SECONDS:
            break
        res = await provider.execute_tool("revit_extract_snapshot", {"cursor": cursor})
    data = assemble_slices(parts, stopped_early=stopped_early, changed_during_capture=changed,
                           elapsed_ms=int((time.monotonic() - started) * 1000))
    for path in paths:
        _discard_part_file(path, snapshot_id)
    return data


async def _extract_live(provider: Any, payload: Dict[str, Any]):
    """Run one extraction. Returns (kind, data, result): kind is inline, sliced or file."""
    res = await provider.execute_tool("revit_extract_snapshot", dict(payload))
    if isinstance(res, dict) and "snapshot" in res:
        return "inline", dict(res["snapshot"]), res
    if isinstance(res, dict) and res.get("sliced") is True:
        return "sliced", await _collect_slices(provider, res), res
    if isinstance(res, dict) and res.get("snapshot_id") and res.get("path"):
        # Add-in result: the snapshot was written to disk, not returned inline.
        return "file", _read_json_file(res["path"]), res
    raise RuntimeError(f"Unexpected result from Revit snapshot extraction: {sorted(res) if isinstance(res, dict) else type(res).__name__}")


def _finish_live(workspace: Any, kind: str, data: Dict[str, Any], res: Dict[str, Any]) -> Snapshot:
    if kind == "inline":
        return Snapshot(**data)
    if kind == "sliced":
        return _save_snapshot_data(workspace, data)
    snapshot = Snapshot(**data)
    _store_snapshot_file(workspace, snapshot.snapshot_id, res["path"])
    return snapshot


async def snapshot_take(workspace: Any, bridge_client_or_provider: Any = None, options: Any = None) -> Snapshot:
    """Capture a snapshot of the active model and save it in the workspace.

    Options: categories, max_elements, params (read only these parameters), slice_size (extract over
    several Revit turns and assemble one snapshot), base_snapshot_id (incremental: re-read only what
    changed since that snapshot and merge; falls back to a full capture and says why in
    counts.incremental_reason).
    """
    from revit_mcp_server.config import BridgeMode, config

    options = dict(options or {})
    payload = _snapshot_payload(options)
    base_id = options.get("base_snapshot_id")
    base_data: Optional[Dict[str, Any]] = None
    base_problem: Optional[str] = None
    if base_id is not None:
        base_data = _load_snapshot_data(workspace, base_id)
        base_problem = incremental_base_problem(base_data, payload)

    live = config.mode != BridgeMode.mock
    if bridge_client_or_provider and hasattr(bridge_client_or_provider, "execute_tool"):
        provider = bridge_client_or_provider
        try:
            if base_data is None:
                kind, data, res = await _extract_live(provider, payload)
                return _finish_live(workspace, kind, data, res)

            if base_problem is None:
                tracker = base_data["counts"]["tracker"]
                kind, data, res = await _extract_live(
                    provider, {**payload, "base_epoch": tracker["epoch"], "base_seq": tracker["seq"]})
                if kind == "file" and data.get("incremental") is True:
                    try:
                        merged = merge_incremental(base_data, data, base_id)
                    except IncrementalMergeError as e:
                        _discard_part_file(res["path"], str(data.get("snapshot_id")))
                        base_problem = f"The incremental capture could not be merged ({e}); a full snapshot was taken."
                        kind, data, res = await _extract_live(provider, payload)
                    else:
                        _discard_part_file(res["path"], str(merged.get("snapshot_id")))
                        return _save_snapshot_data(workspace, merged)
                else:
                    base_problem = (
                        (res.get("incremental_reason") if isinstance(res, dict) else None)
                        or (data.get("counts") or {}).get("incremental_reason")
                        or "The Revit add-in did not return an incremental capture (it may predate incremental "
                           "snapshots); a full snapshot was taken."
                    )
            else:
                base_problem = f"{base_problem} A full snapshot was taken."
                kind, data, res = await _extract_live(provider, payload)

            counts = data.setdefault("counts", {})
            counts["incremental"] = False
            counts["incremental_reason"] = base_problem
            counts["base_snapshot_id"] = base_id
            return _save_snapshot_data(workspace, data)
        except Exception as e:
            if live:
                raise RuntimeError(
                    f"Could not capture a live snapshot from Revit: {e}. "
                    "No mock data is substituted in bridge mode."
                ) from e
            logger.warning(f"Failed to extract snapshot from Revit host: {e}. Falling back to mock snapshot.")
    elif live:
        raise RuntimeError("No Revit provider is available to capture a live snapshot; no mock data is substituted in bridge mode.")

    snapshot = generate_mock_snapshot()
    if payload.get("params"):
        project_snapshot_params(snapshot, payload["params"])
    if base_id is not None:
        snapshot.counts["incremental"] = False
        snapshot.counts["incremental_reason"] = "Mock mode has no change journal; a full mock snapshot was generated."
        snapshot.counts["base_snapshot_id"] = base_id

    # Store snapshot in workspace/snapshots folder
    snapshots_dir = workspace.allowed_directories[0] / "snapshots"
    from revit_mcp_server.security.safe_paths import snapshot_file

    snapshot_path = snapshot_file(snapshots_dir, snapshot.snapshot_id)
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    with open(snapshot_path, "w", encoding="utf-8") as f:
        f.write(snapshot.model_dump_json(by_alias=True, indent=2))

    return snapshot

def snapshot_query(snapshot: Snapshot, filter_dsl: Dict[str, Any]) -> List[ElementRecord]:
    results = []
    
    for el in snapshot.elements:
        match = True
        for key, val in filter_dsl.items():
            if key == "category":
                if isinstance(val, list):
                    if el.category not in val:
                        match = False
                elif el.category != val:
                    match = False
            elif key == "family" and el.family != val:
                match = False
            elif key == "type_name" and el.type_name != val:
                match = False
            elif key == "level_uid" and el.level_uid != val:
                match = False
            elif key == "workset" and el.workset != val:
                match = False
            elif key == "group_uid" and el.group_uid != val:
                match = False
            elif key == "placed":
                # unplaced/placed for rooms
                is_placed = el.level_uid is not None or (el.location is not None and el.location.xyz is not None)
                if val is True and not is_placed:
                    match = False
                elif val is False and is_placed:
                    match = False
            elif key == "parameter":
                # validate parameter requirements
                param_name = val.get("name")
                if param_name:
                    param = el.params.get(param_name)
                    if val.get("empty") is True:
                        if param is not None and param.v is not None and param.v != "":
                            match = False
                    elif "value" in val:
                        expected = val["value"]
                        if param is None or str(param.v) != str(expected):
                            match = False
                            
        if match:
            results.append(el)
            
    return results

def snapshot_diff(snapshot_a: Snapshot, snapshot_b: Snapshot) -> Dict[str, List[Any]]:
    elements_a = {el.uid: el for el in snapshot_a.elements}
    elements_b = {el.uid: el for el in snapshot_b.elements}
    
    added = []
    deleted = []
    modified = []
    
    # 1. Added/Modified
    for uid, el_b in elements_b.items():
        if uid not in elements_a:
            added.append(el_b)
        else:
            el_a = elements_a[uid]
            # Check if modified
            is_mod = False
            
            # Simple metadata checks
            if el_a.type_uid != el_b.type_uid or el_a.level_uid != el_b.level_uid:
                is_mod = True
                
            # Location check
            if el_a.location != el_b.location:
                is_mod = True
                
            # Parameter check
            if el_a.params != el_b.params:
                is_mod = True
                
            if is_mod:
                modified.append(el_b)
                
    # 2. Deleted
    for uid in elements_a:
        if uid not in elements_b:
            deleted.append(uid)
            
    return {
        "added": added,
        "deleted": deleted,
        "modified": modified
    }

def reconcile_delta(
    base: Snapshot, 
    target: Snapshot, 
    live: Snapshot
) -> Dict[str, Any]:
    base_elements = {el.uid: el for el in base.elements}
    live_elements = {el.uid: el for el in live.elements}
    
    conflicts = []
    actions = []
    
    # Identify target modifications or deletions
    target_diff = snapshot_diff(base, target)
    
    # 1. Handle Deleted Elements
    for uid in target_diff["deleted"]:
        # Check if modified in live since base
        base_el = base_elements.get(uid)
        live_el = live_elements.get(uid)
        if base_el and live_el:
            # If live was modified compared to base
            if live_el.params != base_el.params or live_el.location != base_el.location:
                conflicts.append({
                    "uid": uid,
                    "reason": "Element was modified in the live model but is slated for deletion in the target plan."
                })
                continue
        actions.append({
            "action": "delete",
            "uid": uid,
            "element_id": base_el.element_id if base_el else None
        })
        
    # 2. Handle Modified Elements
    for target_el in target_diff["modified"]:
        uid = target_el.uid
        base_el = base_elements.get(uid)
        live_el = live_elements.get(uid)
        
        if not base_el or not live_el:
            # Element missing, cannot reconcile modification
            continue
            
        # Check for conflict: has live changed compared to base?
        live_changed = False
        if live_el.location != base_el.location or live_el.params != base_el.params or live_el.type_uid != base_el.type_uid:
            live_changed = True
            
        if live_changed:
            # Check if target values equal live values (safe) or differ (conflict)
            if target_el.location != live_el.location or target_el.params != live_el.params or target_el.type_uid != live_el.type_uid:
                conflicts.append({
                    "uid": uid,
                    "reason": "Element was modified both in the target plan and in the live model since extraction."
                })
                continue
                
        # Generate parameter updates or location updates
        param_updates = {}
        for p_name, p_val in target_el.params.items():
            base_p = base_el.params.get(p_name)
            if not base_p or base_p.v != p_val.v:
                param_updates[p_name] = p_val.v
                
        actions.append({
            "action": "modify",
            "uid": uid,
            "element_id": target_el.element_id,
            "param_updates": param_updates,
            "location": target_el.location.model_dump() if target_el.location else None
        })
        
    # 3. Handle Added Elements
    for target_el in target_diff["added"]:
        actions.append({
            "action": "create",
            "uid": target_el.uid,
            "category": target_el.category,
            "type_uid": target_el.type_uid,
            "level_uid": target_el.level_uid,
            "location": target_el.location.model_dump() if target_el.location else None,
            "params": {k: v.v for k, v in target_el.params.items()}
        })
        
    return {
        "conflicts": conflicts,
        "actions": actions,
        "reconciled_at": datetime.now(timezone.utc).isoformat()
    }
