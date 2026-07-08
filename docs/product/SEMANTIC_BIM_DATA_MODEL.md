# Semantic BIM Data Model

The shared data layer that W1/W7/W5 (MVP) and W11/W14 (roundtrip) all consume. Builds on the existing `IdentityMapper` (`aec_translate_id`, `aec_register_mapping`) and `SemanticGraph` provider; adds the element-level **snapshot** and **roundtrip** schemas that don't exist yet.

## 1. Identity strategy

- **Primary key: Revit `UniqueId`** (episode GUID + id — stable across sessions, survives central/local roundtrips). Every record, finding, mapping, and audit entry keys on it.
- **`ElementId` is a cache, never persisted as identity** — it can change (workshared reassignments, audit ops). Stored alongside for fast API calls within a session, always re-resolvable from UniqueId.
- **Cross-app identity** via the existing mapper: `(app, native_id) ↔ amb_uid`. Revit UniqueId, IFC GlobalId, Speckle object id, Rhino object GUID, Navisworks item GUID all register against one `amb_uid` (ULID).
- **Document identity:** Revit `Document.CreationGUID` + `WorksharingCentralGUID` when workshared; SaveAs detection prompts re-anchor (cf. W9 failure case).

## 2. Snapshot schema (JSON, one document per extraction)

```json
{
  "schema": "amb.snapshot/1",
  "snapshot_id": "01J...ULID",
  "taken_at": "2026-07-08T14:02:11Z",
  "source": {
    "app": "revit", "app_version": "2025.2",
    "doc_guid": "...", "central_guid": "...", "doc_title": "Tower_A.rvt",
    "units": "SI", "phase_map": {"3": "Existing", "4": "New Construction"}
  },
  "elements": [ { ...ElementRecord... } ],
  "relations": [ { ...Relation... } ],
  "types": [ { ...TypeRecord... } ],
  "counts": {"by_category": {"OST_Doors": 214}}
}
```

**ElementRecord:**

```json
{
  "uid": "revit-uniqueid-string",
  "amb_uid": "01J...",
  "element_id": 316221,
  "category": "OST_Doors",
  "class": "FamilyInstance",
  "type_uid": "type-uniqueid",
  "family": "Door_Single_Flush", "type_name": "0915 x 2134mm",
  "level_uid": "…", "phase_created": 4, "phase_demolished": null,
  "design_option": null, "workset": "Shell",
  "group_uid": null, "host_uid": "wall-uniqueid",
  "room_uids": {"from": "…", "to": "…"},
  "location": {"kind": "point", "xyz": [12.4, 3.1, 0.0], "rotation": 1.5708},
  "bbox": {"min": [..], "max": [..]},
  "params": {
    "Mark": {"v": "D-104", "storage": "String", "instance": true, "readonly": false},
    "FireRating": {"v": null, "storage": "String", "instance": true, "readonly": false},
    "Width": {"v": 0.915, "storage": "Double", "spec": "Length", "instance": false}
  },
  "geometry_ref": {"kind": "none|bbox|mesh_uri", "uri": null},
  "materials": ["mat-uid-1"]
}
```

Notes:
- **Units: SI internally everywhere** (metres/radians), matching the Rhino bridge convention; converters at the edges only.
- `params` carries storage type + spec + writability → plan-time validation for W5 needs no extra round-trip.
- `geometry_ref` keeps snapshots light: geometry is *referenced* (bbox by default; mesh exported on demand to workspace files), never inlined. BIM semantics travel; dumb geometry stays home.

**Relations** (edges, feeding/mirroring the existing `graph_*` provider):

```json
{"kind": "hosts",       "from": "wall-uid",  "to": "door-uid"}
{"kind": "bounds",      "from": "room-uid",  "to": "wall-uid"}
{"kind": "on_level",    "from": "door-uid",  "to": "level-uid"}
{"kind": "in_group",    "from": "elem-uid",  "to": "group-uid"}
{"kind": "opening_in",  "from": "opening-uid","to": "wall-uid"}
{"kind": "on_sheet",    "from": "view-uid",  "to": "sheet-uid"}
{"kind": "references_grid", "from": "col-uid", "to": "grid-uid"}
```

Wall/opening/window/door chains are thus first-class queryable: `door —hosted_by→ wall ←opening_in— opening`, room adjacency via shared `bounds` walls.

**TypeRecord:** `{uid, category, family, type_name, params{...}, family_source: "system|loadable|inplace"}` — feeds W6 family validation and W11 type mapping.

## 3. Domain specifics

- **Model groups:** `group_uid` on members + `GroupRecord {uid, group_type_uid, member_uids[], instance_count}`; W3/W4 read this, never raw geometry.
- **Rooms/spaces:** placed/unplaced/unenclosed state captured at extraction (`placed: bool`, `area: m²`, `bounding: [wall_uids]`) — the W7 room rules run on snapshot alone.
- **Levels/grids:** always extracted (cheap, universally referenced); elements carry `level_uid` + optional grid refs.
- **Materials/layers:** `MaterialRecord {uid, name, class, appearance_hash}`; wall compound structure as ordered layer list on the TypeRecord — needed for façade/IFC comparisons.
- **Façade zones (W11):**

```json
{
  "schema": "amb.facade_zone/1",
  "zone_id": "tower-a-south",
  "host": {"kind": "loft_surface|curtain_system|mass_face", "ref": "rhino:guid|revit:uid"},
  "grid": {"u_divs": 20, "v_divs": 36, "seam": "v0"},
  "panels": [
    {"pid": "A_03_17", "panel_type": "A", "corners_m": [[x,y,z],[..],[..],[..]],
     "target_family": "AMB_GlassPanel_Adaptive", "type_map": "glass-clear",
     "params": {"Area": 2.31}, "amb_uid": null}
  ],
  "counts_expected": {"A": 720, "B": 684, "bot": 36, "top": 36}
}
```

`counts_expected` enforces the no-silent-skip rule (the 1476-panel discipline from CLAUDE.md); `amb_uid` fills on placement → re-apply becomes a diff, not a rebuild.

- **Design variants:** `VariantRecord {variant_id, zone_id, spec_hash, applied_at, plan_id, element_uids[]}` — variants are compared by spec, applied as plans, and reversible as plan inverses.

## 4. Change tracking

- Snapshots are immutable, ULID-ordered. `snapshot_diff(a, b)` → `{added[], removed[], modified[{uid, param_changes{...}, moved: bool}]}`.
- The add-in already hooks `DocumentChanged` — extend it to append touched ElementIds to a session dirty-list, so incremental snapshot refresh extracts only dirty elements (big-model performance, ADR 0007 budgets).
- Audit ledger entries reference `snapshot_id` at plan time → every approved change is anchored to what the user actually saw.

## 5. Roundtrip format (W14)

A **delta document** — the only thing external tools (GH, Excel, Speckle apps) send back:

```json
{
  "schema": "amb.delta/1",
  "base_snapshot": "01J...",
  "actions": [
    {"op": "update", "uid": "door-uid", "set": {"FireRating": "60"}},
    {"op": "create", "temp_id": "t1", "class": "FamilyInstance",
     "family": "AMB_GlassPanel_Adaptive", "type_name": "glass-clear",
     "placement": {"kind": "adaptive_points", "points_m": [[..],[..],[..],[..]]},
     "set": {"Mark": "P-0317"}},
    {"op": "delete", "uid": "old-panel-uid", "reason": "variant re-apply"}
  ]
}
```

Reconciliation (hub): resolve uids against **live** model → three-way check vs `base_snapshot` (conflict = live changed since base → flag, never overwrite) → produce ActionPlan → approval gate → apply → register created `temp_id → UniqueId` mappings.

## 6. What is needed to recreate native Revit elements

Per creatable class, the delta must carry (validated at plan time, blocked with hints if missing):

| Class | Required |
|---|---|
| Wall | level_uid, wall type (or type_map), location curve (m), height/top constraint, structural flag |
| FamilyInstance (hosted) | family+type loadable in doc, host_uid, placement point/face ref, level_uid |
| FamilyInstance (adaptive) | family+type, N adaptive points in order |
| Floor/Roof | level_uid, type, boundary loops (m), slope data |
| Room | level_uid, phase, location point (placed) — geometry comes from bounding walls |
| Sheet/View | titleblock type / view template uid, number+name (uniqueness pre-checked) |
| Group instance | group_type_uid, insertion point |

Type-mapping tables (`familytype_mapper` module) translate external names → loaded Revit types; unresolvable mappings are plan blockers, **never** DirectShape fallbacks unless the user explicitly opts in (`fallback: "directshape_preview"`).

## 7. Storage

- Snapshots/deltas: JSON (gzip) in workspace `snapshots/`; latest also mirrored to SQLite via existing `exporter_to_sqlite` schema for SQL querying (one schema, documented, `schema_version` column).
- Mappings: existing mapper store. Issues: `issues.sqlite` (W9). Audit: JSONL ledger (architecture §5).
