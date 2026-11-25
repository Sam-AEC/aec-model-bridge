# ADR 0010: Semantic BIM Snapshot & Delta Schema

## Status
Accepted

## Context
Exchanging heavy geometry representations (like meshes or direct shapes) between BIM tools and LLM agents is slow, expensive, and strips the model of its structural semantics (levels, parameters, relationships). To enable efficient querying (W1), compliance rules (W7), and parameter batching (W5), we need a lightweight, semantic snapshot model that captures BIM elements, parameters, and relationships in a flat JSON structure.

## Decisions

### 1. Identity Strategy
- **Primary Element Identifier**: Revit `UniqueId` (stable GUID + ID) is used as the global primary key. Revit `ElementId` is treated as a temporary session-based cache and is never persisted across sessions.
- **Cross-App Identity**: Multi-platform elements (Revit, Rhino, IFC) are mapped to a unified `amb_uid` (ULID) via the `IdentityMapper` registry.
- **Document Identifier**: Document tracking uses `Document.CreationGUID` combined with `WorksharingCentralGUID` (for workshared central files) to detect SaveAs actions.

### 2. Snapshot Schema
A **Snapshot** is a JSON document containing flat element records, relational edges, type data, and Category counts:

```json
{
  "schema": "amb.snapshot/1",
  "snapshot_id": "01J...ULID",
  "taken_at": "2026-07-08T18:07:30Z",
  "source": {
    "app": "revit",
    "app_version": "2025.2",
    "doc_guid": "...",
    "doc_title": "model.rvt",
    "units": "SI"
  },
  "elements": [
    {
      "uid": "revit-unique-id-string",
      "amb_uid": "01J...",
      "category": "OST_Doors",
      "family": "Single-Flush",
      "type_name": "0915x2134mm",
      "level_uid": "level-uid-string",
      "host_uid": "wall-uid-string",
      "location": {"kind": "point", "xyz": [10.2, 5.4, 0.0], "rotation": 1.57},
      "params": {
        "Mark": {"v": "101", "storage": "String", "instance": true, "readonly": false},
        "FireRating": {"v": "30", "storage": "String", "instance": true, "readonly": false}
      }
    }
  ],
  "relations": [
    {"kind": "hosts", "from": "wall-uid-string", "to": "revit-unique-id-string"},
    {"kind": "on_level", "from": "revit-unique-id-string", "to": "level-uid-string"}
  ]
}
```

### 3. Standards and Units
- **Internal Units**: All coordinates, rotation angles, areas, and volumes are stored internally in standard SI units (metres, radians, square metres, cubic metres), matching the Rhino bridge convention.
- **Lightweight Geometry**: Elements carry basic bounding box dimensions (`bbox`) or location markers. Meshes are only exported on-demand to separate files, not inline in the snapshot.

### 4. Incremental Change Tracking
- **Session Dirty-List**: The C# add-in hooks `DocumentChanged` events to append modified/created elements to a session dirty-list.
- **Incremental Extraction**: The hub uses the dirty-list to pull only changed elements during active sessions, resolving large-model performance risks (ADR 0007).
- **Snapshot Diffing**: `snapshot_diff(a, b)` generates parameter-level and relational differences between versioned snapshots.

### 5. Delta Roundtrip Schema
Modifications sent from external tools (Grasshopper, Excel) are structured as transactional deltas:
```json
{
  "schema": "amb.delta/1",
  "base_snapshot": "01J...ULID",
  "actions": [
    {"op": "update", "uid": "door-uid", "set": {"FireRating": "60"}},
    {"op": "create", "temp_id": "t1", "class": "FamilyInstance", "family": "GlassPanel", "type_name": "Clear", "placement": {"kind": "adaptive_points", "points_m": [[0,0,0], [1,0,0], [1,1,0], [0,1,0]]}}
  ]
}
```

### 6. Optional blocks (`include`)
`snapshot_take` and `revit_extract_snapshot` accept `include`, a list of block names. Without it the snapshot has the keys above and nothing else. The schema stays `amb.snapshot/1`; the keys below are optional, and a reader that does not know them ignores them. Each block adds capture time, so each is off by default. `counts.include` lists the blocks a snapshot was taken with.

| Block | Keys it adds | Read by |
|---|---|---|
| `types` | top-level `types`: one record per loadable family type, in-place family type and system host type (wall, floor, roof, ceiling): `uid` (the type ElementId as text, the value elements carry in `type_uid`), `category`, `family`, `type_name`, `family_source` (`system`, `loadable` or `inplace`), `params`, `instance_count` (placed instances in the whole document, not only the captured elements) | `model_bloat_audit` |
| `cad` | top-level `cad_scanned: true` and `cad`: one record per imported or linked CAD file: `element_id`, `name`, `is_link`, `view_specific`. A link with no placed instance is listed once, from its type | `model_bloat_audit` |
| `rooms` | on every door, the parameters `From Room` and `To Room` (value: the room UniqueId, empty when there is no room on that side); on every room, `level_uid` and `location` (`kind: point`, rotation 0) | `schedule_consistency` |

Rules:
- A block that could not be read completely is left out and not written as empty. `types` stops at its own time budget (the `time_budget_ms` of the call) and then writes no `types` and sets `counts.types_truncated`. `cad_scanned` is written only after the scan finished. A reader that finds the key missing reports "not enough data", never a pass.
- An old snapshot without these keys still loads and the audits still say "not enough data" for it.
- `model_bloat_audit` uses `instance_count` when every type has one. Otherwise it counts the captured elements that point at each type, as before.
- `rooms` is always a full capture: an incremental capture (`base_snapshot_id`) with `rooms`, or against a base taken with other blocks, falls back to a full snapshot and says why in `counts.incremental_reason`. A door's rooms can change without the door changing.
- `include` is refused with the list of known blocks when it holds any other name.
- Not stored: nested and shared family usage, types used only by other types.
- UNVERIFIED in live Revit: the add-in reading (`FamilyInstance.FromRoom` and `ToRoom` use the last phase of the project, the `ImportInstance` and `CADLinkType` names, and the capture time on a large model). The add-in compiles against Revit 2024; the server side is tested on hand-built snapshots.

## Consequences
- **High Performance**: Snapshots of 10k-element models are lightweight and can be parsed in seconds rather than minutes.
- **Offline QA Checks**: QA/QC rule engines can run rule evaluations against the local SQLite-mirrored snapshot database without blocking the live Revit API thread.
- **Conflict Prevention**: Reconciling delta files against live snapshots detects if elements were modified by other team members since the base snapshot was taken, preventing data loss.
