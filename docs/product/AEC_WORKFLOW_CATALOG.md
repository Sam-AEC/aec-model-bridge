# AEC Workflow Catalog

Each workflow lists: user story · input → output · Revit objects · MCP tools (existing tool names verbatim; **[NEW]** = to build) · modules · UI · safety · failure cases · validation · MVP vs advanced. Modules refer to `PLUGIN_MODULE_SYSTEM.md`; safety gate refers to `PLUGIN_APP_ARCHITECTURE.md` §4.

Tiers: **T1** = MVP (read + gated write), **T2** = flagship/post-MVP, **T3** = later phases.

---

## W1 — Ask AI about the current model (T1)

- **Story:** "As a BIM coordinator I ask 'how many doors on Level 3 have no fire rating?' and get an answer with clickable element IDs in under a minute."
- **In:** natural-language question. **Out:** answer + element UniqueId list + optional saved query.
- **Revit objects:** any FilteredElementCollector-reachable element; Levels, Categories, Parameters.
- **Tools:** `revit_get_document_info`, `revit_list_elements`, `revit_get_elements_by_type`, `revit_get_element_parameters`, `revit_list_levels`, `revit_get_categories`, `snapshot_query` **[NEW]** (query the semantic snapshot instead of N round-trips).
- **Module:** Model Inspector. **UI:** panel chat; results as element chips → click = `revit_set_selection` + zoom.
- **Safety:** read-only — no gate. Token guard: cap result payloads; large queries via snapshot, not element-by-element.
- **Failures:** no doc open (`revit_health` first); stale snapshot (show snapshot age, offer refresh); param name ambiguity (ask user).
- **Validation:** cross-check counts against a Revit schedule on the test model.
- **MVP:** count/filter/list on snapshot. **Advanced:** multi-hop questions via `graph_query_relations`, saved queries as QA rules.

## W2 — Inspect selected elements (T1)

- **Story:** "I select elements and ask 'what is this and what's wrong with it?'"
- **In:** live selection. **Out:** type/family/host/level/params card + rule findings.
- **Tools:** `revit_get_selection`, `revit_get_element_parameters`, `revit_get_element_type`, `revit_get_element_bounding_box`, `revit_get_warnings`.
- **Module:** Selection Tools + Model Inspector. **UI:** ribbon "Inspect Selection" + panel card. **Safety:** read-only.
- **Failures:** empty selection; view-specific elements; huge selections (summarize, don't enumerate).
- **Validation:** matches Revit Properties palette on test model.
- **MVP:** property card. **Advanced:** per-selection QA findings, "fix" suggestions feeding W5.

## W3 — Extract model groups (T1)

- **Story:** "List all model groups, members, and instance counts so I can audit group hygiene."
- **In:** none/filter. **Out:** group table (name, instances, member categories, nesting).
- **Revit objects:** `Group`, `GroupType`. **Tools:** `revit_list_elements` (OST_IOSModelGroups), `revit_get_group_members`.
- **Module:** Model Inspector. **UI:** panel table + CSV export. **Safety:** read-only.
- **Failures:** nested groups (recurse with depth cap); groups in links (out of scope, flag).
- **MVP:** table. **Advanced:** duplicate-group detection, group-vs-group diff.

## W4 — Manipulate model groups safely (T1, gated)

- **Story:** "Rename/ungroup/convert selections to groups in bulk without corrupting instances."
- **In:** group selection + operation. **Out:** applied changes + audit entries.
- **Tools:** `revit_create_group`, `revit_ungroup`, `revit_convert_to_group`, `revit_move_element`, `plan_actions` **[NEW]**.
- **Module:** Selection Tools. **UI:** plan cards in approval queue. **Safety:** ActionPlan required; ungroup flagged destructive; per-plan TransactionGroup.
- **Failures:** group instances in other views/phases (report affected count in plan); attached details lost on ungroup (warn).
- **Validation:** instance counts before/after; Revit undo restores exactly.
- **MVP:** rename/ungroup with plan preview. **Advanced:** re-group after edit, group content sync.

## W5 — Read & update parameters (T1, gated — killer workflow #3)

- **Story:** "Set `FireRating='60'` on all EI-60 doors; I see the before/after diff, approve, and can roll back."
- **In:** filter + param + value (or CSV mapping). **Out:** diff table → applied plan → audit + inverse plan.
- **Tools:** `revit_get_element_parameters`, `revit_get_parameter_value`, `revit_set_parameter_value`, `revit_batch_set_parameters`, `revit_batch_set_parameters_by_filter`, `revit_get_type_parameters`, `revit_set_type_parameter`, `plan_actions` **[NEW]**.
- **Module:** Parameter Manager. **UI:** diff grid (element, param, before → after) with per-row/all approve.
- **Safety:** capture before-values (enables inverse plan); read-only params and type-vs-instance mismatches blocked at plan time; storage-type validation (string/double/ElementId); unit handling via spec type.
- **Failures:** param not bound on category; workshared element owned by other user (report, skip, list); formula-driven params (read-only).
- **Validation:** re-read after apply == intended; undo restores before-values on test model.
- **MVP:** filter-based batch set with diff+approval. **Advanced:** CSV/Excel roundtrip, shared-param creation (`revit_create_shared_parameter`), rule-driven fixes from W7.

## W6 — Validate families & types (T1)

- **Story:** "Flag families that break our standard: naming, duplicate types, oversized, in-place."
- **In:** ruleset (naming regex, size caps, banned categories). **Out:** findings list per family/type.
- **Tools:** `revit_list_families`, `revit_get_type_parameters`, `revit_get_elements_by_type`, `revit_edit_family` (advanced), `snapshot_query` **[NEW]**.
- **Module:** Family/Type Mapper + QA/QC Checker. **UI:** findings table, severity-grouped. **Safety:** read-only (fixes route through W5/W9 plans).
- **Failures:** family size requires doc extraction (defer to advanced); in-place families lack types (special-case).
- **MVP:** naming + duplicate-type + in-place count checks. **Advanced:** type-catalog compliance, `revit_replace_family_type` remediation plans.

## W7 — Model health checks: walls/doors/windows/rooms/levels/views/sheets/schedules (T1 — killer workflow #2)

- **Story:** "One click, model health report in 2 minutes: unplaced rooms, unnamed views, doors without hosts, duplicate marks, views-not-on-sheets…"
- **In:** ruleset id (YAML rule packs). **Out:** findings report (severity, rule, elements, suggested fix).
- **Revit objects:** Walls, Doors, Windows, Openings, Rooms, Levels, Views, ViewSheets, Schedules, Warnings.
- **Tools:** snapshot + `revit_get_warnings`, `revit_list_views`, `revit_list_sheets`, `revit_get_schedule_data`, `revit_list_levels`, `graph_audit_disconnected`, `graph_audit_clashes`; `run_qa_ruleset` **[NEW]**.
- **Module:** QA/QC Checker. **UI:** ribbon "Run Health Check" → progress (JobManager) → report in panel; export via W8.
- **Safety:** read-only; suggested fixes become ActionPlans only on user click.
- **Failures:** huge models → async job with progress (`job_status`); rules referencing unbound params → rule skipped + noted, not crash.
- **Validation:** seeded test model with known defects → rule pack finds exactly those (golden findings file in CI).
- **MVP:** ~15 core rules (unplaced/unenclosed rooms, unnamed/duplicate views, views not on sheets, doors/windows without host, duplicate marks, untagged doors, warning count by type, empty schedules, model group count sanity, unused families threshold). **Advanced:** firm-custom rule packs, IDS-based checking, scheduled runs, trend tracking across snapshots.

## W8 — Generate BIM reports / export structured data (T1)

- **Story:** "Export model + QA findings to SQLite/Excel; my Power BI dashboard refreshes from it."
- **In:** snapshot + findings. **Out:** `.sqlite` / `.xlsx` / (later `.parquet`).
- **Tools:** `exporter_to_sqlite`, `exporter_graph_to_sqlite`, `exporter_db_health`, `export_excel` **[NEW]** (openpyxl), `revit_get_schedule_data`.
- **Module:** Report Generator + Data Exporter. **UI:** ribbon "Reports" → format + destination (workspace-sandboxed paths).
- **Safety:** writes only inside workspace sandbox (exists); redaction on paths/PII (exists).
- **Failures:** file locked by Excel/PBI (retry w/ timestamped name); schema drift between exports (schema_version column).
- **MVP:** SQLite + Excel with fixed schema. **Advanced:** Parquet/DuckDB, `.pbit` template auto-refresh, scheduled exports.

## W9 — QA/QC issue lists (T1)

- **Story:** "Findings become a tracked issue list I can assign, mark resolved, and re-check."
- **In:** W7 findings. **Out:** issue records (id, rule, elements, status, assignee) persisted per document GUID; re-run auto-resolves fixed issues.
- **Tools:** `run_qa_ruleset` **[NEW]**, issue store **[NEW]** (SQLite in workspace), `autodesk_data_create_issue` (advanced → ACC), `speckle_send_object` (advanced).
- **Module:** QA/QC Checker. **UI:** issues tab in panel; click issue → select+zoom elements.
- **Safety:** issue store is external metadata — no model writes.
- **Failures:** elements deleted since finding (mark orphaned via UniqueId miss); doc SaveAs changes GUID (re-anchor prompt).
- **MVP:** local issue store + re-check lifecycle. **Advanced:** ACC Issues / BCF export, assignment via email.

## W10 — Automate view/sheet workflows (T1, gated)

- **Story:** "Create 40 sheets from CSV, place plans, populate title blocks, renumber — as one approved plan."
- **Tools (all exist):** `revit_batch_create_sheets_from_csv`, `revit_create_sheet`, `revit_place_viewport_on_sheet`, `revit_populate_titleblock`, `revit_list_titleblocks`, `revit_renumber_sheets`, `revit_duplicate_sheet`, `revit_create_floor_plan_view`, `revit_apply_view_template`, `revit_get_view_templates`.
- **Module:** View/Sheet Automator. **UI:** CSV picker + preview table (sheet number/name/view/titleblock) → approve.
- **Safety:** duplicate-sheet-number pre-check at plan time; deletes (`revit_delete_sheet`) always destructive-flagged.
- **Failures:** titleblock family missing (halt plan with fix hint); viewport placement collisions (grid heuristic + report).
- **Validation:** sheet count/numbers match CSV exactly; undo removes all created sheets (TransactionGroup).
- **MVP:** CSV → sheets + titleblock params. **Advanced:** auto viewport layout, revision management (`revit_get_revision_sequences`), print/export sets.

## W11 — Façade configurator (T2 — flagship)

- **Story:** "I tune a diagrid façade in Rhino/GH; approved panel layout lands in Revit as native curtain panels/adaptive components with type mapping and parameters — not DirectShape."
- **In:** GH/Rhino panel geometry + `facade_zone` semantic spec (see `SEMANTIC_BIM_DATA_MODEL.md` §facade). **Out:** native Revit elements + identity mappings + variant record.
- **Revit objects:** Curtain systems/panels, adaptive component families, mullions, reference points.
- **Tools:** `rhino_run_python`, `rhino_generate_diagrid_tower`, `rhino_get_scene`, `aec_register_mapping`, `aec_translate_id`, `revit_place_family_instance`, `revit_batch_set_parameters`, `facade_apply_zone` **[NEW]** (semantic spec → placement plan); preview via DirectShape **only** with visible "PREVIEW" marker + auto-cleanup.
- **Modules:** Façade Configurator + Rhino Bridge. **UI:** variant cards (panel counts, type breakdown, deltas vs current) → approve variant.
- **Safety:** variant apply = one TransactionGroup; re-apply diffs against mapped identities (update/create/delete sets shown before approval); deletes always itemized.
- **Failures:** adaptive family missing (block with load instruction); panel outside tolerance of host face (report skipped panels — never silently skip: count must reconcile, cf. the 1476-panel discipline in CLAUDE.md); unit mismatches (metres end-to-end, exists in Rhino bridge).
- **Validation:** panel count Rhino == Revit == mapping table; roundtrip re-export matches within tolerance.
- **MVP(T2):** one zone, one adaptive family, apply + re-apply diff. **Advanced:** multi-zone, type optimization (panel similarity clustering), GH live-link via `g1_*`/Rhino.Inside.

## W12 — Rhino.Inside.Revit workflows (T2)

- **Story:** "Run GH definitions against live Revit geometry inside the Revit process; results land as native elements through the same approval gate."
- **Method:** RiR as *execution backend* — GH definition emits our semantic spec (JSON), hub turns it into an ActionPlan. Custom GH components **[NEW]** wrap hub endpoints.
- **Tools:** `facade_apply_zone` **[NEW]**, `aec_*` mapper; RiR-side components **[NEW]**.
- **Safety:** identical gate — RiR gets no write bypass. **Failures:** RiR version/Rhino version matrix (document supported pairs); unit system differences.
- **MVP(T2):** one exemplar GH definition → semantic spec → native elements. **Advanced:** bidirectional (Revit selection → GH input).

## W13 — Grasshopper/Dynamo workflows (T2/T3)

- **GH (T2):** via Rhino bridge `rhino_run_python` + existing MCP `g1_*` canvas tools; GH exports semantic spec, not meshes. Existing scratch assets (`facade_gh_builder.py`, `facade_system.gh`) become the exemplar.
- **Dynamo (T3):** Dynamo package **[NEW]** with ZeroTouch nodes calling hub HTTP endpoints; same spec, same gate. `scratch/facade_dyn_builder.py` is prior art.
- **Failures:** graph solves mid-edit producing partial specs → spec must carry `complete: true` flag; version pinning of node packages.
- **MVP(T2):** GH exemplar. **Advanced:** Dynamo node package, graph-as-module registration.

## W14 — Semantic roundtrip back to Revit (T2 — the differentiator)

- **Story:** "External tools edit *data about* elements (a JSON of walls/panels/params); the bridge reconciles it into the live model as native edits."
- **In:** semantic delta document (schema §roundtrip). **Out:** reconciliation plan (create/update/delete/skip) → approved apply → updated mappings.
- **Tools:** `snapshot_export` **[NEW]**, `snapshot_diff` **[NEW]**, `plan_actions` **[NEW]**, `aec_translate_id`, all relevant `revit_create_*`/`revit_set_*`.
- **Safety:** three-way awareness — delta vs snapshot vs live model; if live model changed since snapshot, conflicting actions are flagged, never auto-overwritten.
- **Failures:** UniqueId misses (element deleted) → orphan report; type not loadable → blocked action with hint.
- **Validation:** apply → re-export → diff == empty.
- **MVP(T2):** parameters + placement of known families. **Advanced:** geometry-bearing types (walls by curve, floors by boundary), variant management.

## W15 — IFC / Navisworks / Speckle workflows (T2/T3)

- **IFC (T1-adjacent, tools exist):** open IFC alongside RVT — `ifc_get_spatial_structure`, `ifc_query_elements`, `ifc_get_properties`, `ifc_validate`; map to Revit via `aec_register_mapping` (GlobalId ↔ UniqueId, mapper exists). MVP: IFC Q&A + Revit-vs-IFC param comparison.
- **Navisworks (T2):** register `NavisworksProvider` in shipped hub **[fix]**, widen provider to the 16 C# commands (model tree, viewpoints, `navis.run_clash_test`, `navis.get_clash_results`); clash results → identity mapper → Revit element selection ("show me clash #12 in Revit"). Failure: clash GUID ↔ Revit UniqueId mapping fidelity — validate on test pair.
- **Speckle (T2, 17 tools exist):** publish semantic snapshots as Speckle versions (`speckle_publish_version`), receive external edits → W14 reconciliation. Failure: OAuth expiry mid-job (refresh flow exists).

## W16 — Excel / Power BI workflows (T1 Excel, T2 PBI)

- **Story:** "Model data and QA trends in the tools management already uses."
- **Excel (T1):** `export_excel` **[NEW]** — elements/params/findings sheets; CSV param roundtrip back through W5 plans.
- **Power BI (T2):** wire orphaned `PowerBIProvider` **[fix]** → `powerbi_execute_dax` against live PBI Desktop (:3006 external tool exists in C#); or file-based: SQLite/Parquet + provided `.pbit` template (roadmap Phase D).
- **Failures:** ADOMD connection lifetime (PBI restarts change server/db args — re-handshake); Excel file locks.
- **MVP:** Excel export. **Advanced:** DAX Q&A ("ask your dashboard"), auto-refresh pipeline, DuckDB layer.

---

## Cross-cutting requirements

1. Every T1 write workflow goes through **ActionPlan → approval → named transaction → audit → inverse plan** without exception.
2. Every workflow must work on the **canonical test model** (Phase 17) with golden outputs in CI.
3. Every workflow's tool calls appear in `tools-generated.md` with correct mutation metadata.
4. Payload discipline: snapshot-first querying; never stream 50k elements through chat context.
