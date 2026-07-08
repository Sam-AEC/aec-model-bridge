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

## Consequences
- **High Performance**: Snapshots of 10k-element models are lightweight and can be parsed in seconds rather than minutes.
- **Offline QA Checks**: QA/QC rule engines can run rule evaluations against the local SQLite-mirrored snapshot database without blocking the live Revit API thread.
- **Conflict Prevention**: Reconciling delta files against live snapshots detects if elements were modified by other team members since the base snapshot was taken, preventing data loss.
