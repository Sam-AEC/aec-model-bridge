# Scaffolding Task List

Buildable backlog for the agent swarm (roster + rules in `AI_AGENT_SWARM_PLAN.md`). Every phase carries: Epic · Subtasks · Owner · Files · Notes (technical / Revit-BIM concepts / integration points) · Tests · Acceptance / DoD · Dependencies · Risks. Task IDs `P<phase>.<n>`. MVP = Phases 0–10 + 16–19 subset (see `MVP_EXECUTION_PLAN.md`).

Global DoD (applies to every phase): builds green (pytest+ruff; `dotnet build` net48+net8), no broken doc links, `tools-generated.md` regenerated if the tool surface changed, handover block written, human sign-off on the phase.

---

## Phase 0 — Repository audit & documentation consolidation
**Epic:** make the repo tell one true story before building on it. **Owner:** Documentation + Repo Audit + Release. **Deps:** none — start immediately.
- P0.1 Present audit §9 deletion list to Sam; on approval remove stray binaries (`docs/Untitled*.3dm*`, `Omni_LiveGeometryStats.csv`), untrack `dist/`, caches, empty `metrics/`; extend `.gitignore`. ⚠ human approval; consider `git rm --cached` vs history rewrite (92 MB files — recommend BFG later, separate decision).
- P0.2 Move `docs/ecosystem-strategy-and-monetization.md` to private repo; leave stub pointer. ⚠ human approval.
- P0.3 Fix `CLAUDE.md`: Navisworks port 3005→3002, replace dead `docs/agent-task-plan.md` pointer with `docs/product/SCAFFOLDING_TASK_LIST.md`, retitle to AEC Model Bridge.
- P0.4 Fix README broken links (`docs/tools.md`, `docs/architecture.md`, `docs/integration-expansion-handover.md`) → real targets; correct Rhino transport description (HTTP :3004, not SSE :9876); mark Navisworks/PowerBI "in progress" honestly.
- P0.5 Rewrite `docs/security.md` against as-built (provider system, ADR 0002, no phantom config keys). Flip ADR 0001 status Proposed→Accepted.
- P0.6 Version reconciliation: bump `pyproject.toml`, `RevitBridge.csproj`, `server.json` to match CHANGELOG 1.2.0 (or re-cut CHANGELOG; Release agent proposes).
- **Tests:** link checker over docs; grep for "3005", "agent-task-plan", "Omni-Bridge" (outside legacy-note contexts) returns nothing.
- **Acceptance/DoD:** fresh reader gets zero contradictions between README, CLAUDE.md, docs/, and code. **Risk:** deleting something Sam wanted (mitigated: list-first rule).

## Phase 1 — Product definition
**Epic:** lock the product package. **Owner:** Product Architect. **Deps:** P0 readable repo.
- P1.1 Review `docs/product/*` (this package) with Sam; resolve open questions in `DECISIONS_AND_RISKS.md`.
- P1.2 Reconcile `docs/roadmap-and-plans.md` with this package (roadmap = strategy narrative; this = buildable plan; add cross-links, delete duplicated phase tables from roadmap).
- P1.3 Update README positioning to the vision doc's one-liner.
- **Acceptance:** Sam signs decisions D-001…D-012; no competing roadmaps. **Risk:** scope re-litigating — timebox.

## Phase 2 — Plugin-style app architecture
**Epic:** freeze contracts so waves can parallelize. **Owner:** Product Architect + MCP Tooling + Revit API. **Deps:** P1.
- P2.1 ADR-0008: approval gate + ActionPlan lifecycle (states: draft→validated→pending→approved/rejected→executed→rolled-back).
- P2.2 ADR-0009: module system (manifest schema v1 frozen from `PLUGIN_MODULE_SYSTEM.md` §2).
- P2.3 ADR-0010: snapshot schema v1 frozen from `SEMANTIC_BIM_DATA_MODEL.md` §2.
- P2.4 ADR-0011: panel architecture (WebView2, message bridge, hub endpoints the panel calls).
- **Acceptance:** four ADRs Accepted; contract-freeze points from swarm plan in force. **Risk:** over-designing before contact with Revit reality — ADRs stay ≤2 pages each.

## Phase 3 — Revit-native foundation
**Epic:** the C# add-in becomes a safe, modern substrate. **Owner:** Revit API (+ Security/Safety review). **Files:** `packages/revit-bridge-addin/src/**`. **Deps:** P2.
- P3.1 Flip Contract v2 to default (LegacyMode opt-in via `MCP_REVIT_LEGACY_PORT=true`); hub discovery via registry files already exists — verify end-to-end. ⚠ human approval (breaks old setups).
- P3.2 Transaction discipline: audit all 110 handlers in `BridgeCommandFactory.cs`; enforce named `Transaction`/`TransactionGroup` pattern (`"AMB: <cmd> #<action_id>"`); thread `action_id` through `/execute` payload.
- P3.3 New command `revit.extract_snapshot` (full + `dirty_only` incremental using the existing `DocumentChanged` hook) emitting ElementRecords per schema; streams to workspace file, returns path + counts (never inline 50k elements).
- P3.4 New command `revit.get_snapshot_delta` (dirty-list since snapshot_id).
- P3.5 Dead-tree resolution: per-subsystem verdict on `src/Commands/**` (revive as `[BridgeCommand]`s or delete). ⚠ human approval on deletes.
- **Revit concepts:** FilteredElementCollector perf, ElementMulticategoryFilter, UniqueId vs ElementId, DocumentChanged, workshared ownership. **Integration:** feeds Phase 6.
- **Tests:** e2e snapshot on canonical model (Phase 17 model, early script version); handler transaction-name audit is a unit test over reflection metadata.
- **Acceptance/DoD:** snapshot of 10k-element model < 30 s full / < 2 s incremental (ADR 0007 spirit); v2 auth on by default; all handlers carry named transactions. **Risks:** perf on huge models (mitigate: parallel param reads are NOT thread-safe — single-thread extraction, measure first); regressions across net48/net8 (CI matrix).

## Phase 4 — MCP tool foundation
**Epic:** one hub, honest metadata, approval gate. **Owner:** MCP Tooling (+ Security/Safety). **Files:** `packages/mcp-server-revit/src/revit_mcp_server/**`. **Deps:** P2 (can start parallel to P3).
- P4.1 Extend `ProviderTool` with `is_mutating/destructive/execution_mode/permissions`; backfill all ~170 tools (mirror C# `[BridgeCommand]` attrs via `/capabilities`).
- P4.2 Approval gate: `plan_actions`, `list_pending_plans`, `approve_plan`, `reject_plan`, `rollback_plan` tools + `ApprovalGate` middleware rejecting un-planned mutating calls when `approval_mode=required`; persist plans + before-state in workspace.
- P4.3 Register `NavisworksProvider` in `mcp_server.py`; widen to the 16 C# commands.
- P4.4 Retire legacy: migrate tests off `server.py` + `tools/` + old `schemas.py`, then archive. ⚠ human approval. Fix or delete the `proxy._connect()` bug with it.
- P4.5 Wire or park `PowerBIProvider` (decision D-009); if wired: register + health-only for now.
- P4.6 Regenerate `docs/tools-generated.md` — no more "?" columns; document gate tools.
- **Tests:** `test_provider_contract.py` asserts metadata on every tool; new `test_approval_gate.py` (mutating-without-plan rejected, plan lifecycle, rollback restores before-state via mock provider).
- **Acceptance/DoD:** single server; every tool metadata-complete; gate enforced; Navisworks reachable. **Risks:** breaking existing users' tool list (additive only; renames need approval), plan-store corruption (atomic writes).

## Phase 5 — Plugin module registry
**Epic:** modules as first-class citizens. **Owner:** Plugin App. **Files:** `revit_mcp_server/modules/__init__.py`, `module_registry.py`, `ModuleProvider` adapter. **Deps:** P4.
- P5.1 ModuleRegistry (discovery: built-in, entry points, user dir; id-collision policy; version gates).
- P5.2 `module.json` validation (JSON Schema), permission enforcement at dispatch, validate/on_result hooks with timeout budget.
- P5.3 `ModuleProvider` exposing module commands as MCP tools; `module_list_commands` endpoint for the panel.
- P5.4 Hello-world module + module-author guide (`docs/module-authoring.md`).
- **Tests:** contract test iterating all discovered modules (schema-valid manifests, schemas resolve, permissions known); hostile-manifest fixtures.
- **Acceptance/DoD:** drop-in module dir appears as tools + panel commands with zero hub code changes. **Risk:** entry-point security (user modules run arbitrary code — document trust model; firm dir requires explicit enable).

## Phase 6 — Semantic BIM data layer
**Epic:** the snapshot/diff/reconcile engine. **Owner:** Semantic BIM Data. **Files:** `revit_mcp_server/semantic/**`, `schemas/amb.snapshot.v1.json` etc. **Deps:** P3 (extract command) + P4.
- P6.1 Pydantic models + JSON Schemas for snapshot/delta/zone/variant (from `SEMANTIC_BIM_DATA_MODEL.md`).
- P6.2 `snapshot_take` (calls `revit.extract_snapshot`, stores, indexes to SQLite via existing exporter), `snapshot_query` (filter DSL used by rules + W1), `snapshot_diff`.
- P6.3 Delta reconciliation → ActionPlan (three-way conflict detection per §5).
- P6.4 Mapper integration: every snapshot registers uids → `amb_uid`.
- **BIM concepts:** UniqueId stability, phase/design-option filtering, workset ownership, storage types + spec units.
- **Tests:** golden snapshot on canonical model; diff of known edit script == expected; conflict fixtures.
- **Acceptance/DoD:** W1 questions answerable from snapshot alone; diff correct on 20-edit scenario. **Risk:** schema churn after freeze (append-only rule).

## Phase 7 — Model inspection workflows (W1–W3)
**Epic:** killer workflow #1 ships. **Owner:** Plugin App (+ QA/QC BIM for query DSL review). **Files:** `modules/model_inspector/**`, `modules/selection_tools/**` (read side). **Deps:** P5+P6.
- P7.1 `model_inspector` module: `ask` (NL → snapshot_query via agent), `summarize_model`, `list_groups`, element chips payload (uid, label, category) for panel.
- P7.2 Selection inspect: `inspect_selection` (W2 card: type/host/level/params/warnings).
- P7.3 Saved queries (named, per-doc, re-runnable).
- **Tests:** query results == Revit schedule counts on canonical model (golden numbers).
- **Acceptance/DoD:** the W1 user story demo runs end-to-end in Claude Code (panel comes in P16). **Risk:** LLM query hallucination → `snapshot_query` DSL is the only query path; agent must emit DSL, hub validates it.

## Phase 8 — Selection & model group workflows (W2 write side, W4)
**Epic:** first gated writes. **Owner:** Plugin App. **Deps:** P7 + gate (P4).
- P8.1 `selection_tools` write side: set/save/restore selections; select-by-query.
- P8.2 Group ops as plans: rename/ungroup/convert (W4) with affected-instance counts in plan preview.
- **Revit concepts:** Group/GroupType semantics, attached details, view-specific membership.
- **Tests:** ungroup plan on canonical model → undo restores; plan preview counts == actual.
- **Acceptance/DoD:** W4 demo with approval + rollback. **Risk:** group edge cases (nested, mirrored) — document unsupported cases explicitly rather than half-support.

## Phase 9 — Parameter / family / type workflows (W5, W6)
**Epic:** killer workflow #3. **Owner:** Plugin App + Revit API (type params edge cases). **Files:** `modules/parameter_manager/**`, `modules/familytype_mapper/**`. **Deps:** P8.
- P9.1 `parameter_manager`: filter → diff grid → plan → apply → inverse plan (before-values). CSV import/export lane.
- P9.2 Plan-time validation: storage type, readonly, binding, type-vs-instance, unit conversion via spec (SI internal).
- P9.3 `familytype_mapper` read side: family audit (W6 core rules), type mapping tables (feeds W11 later).
- **Tests:** batch-set 500 params → re-read == intended; rollback == original; workshared-owned element skip path (mock).
- **Acceptance/DoD:** W5 user story end-to-end incl. rollback; wrong-type writes impossible (blocked at plan). **Risks:** formula/readonly params, shared-param GUID collisions.

## Phase 10 — QA/QC validation workflows (W7, W9)
**Epic:** killer workflow #2. **Owner:** QA/QC BIM. **Files:** `modules/qaqc_checker/**`, `rules/core/**`. **Deps:** P6 (+P9 for fixes).
- P10.1 Rule engine: YAML rule packs (format in `PLUGIN_MODULE_SYSTEM.md` §9) over `snapshot_query` + `graph_*` audits + `revit_get_warnings`; rule failure = reported, never fatal.
- P10.2 Core pack (~15 rules from W7 MVP list) with severities + fix templates.
- P10.3 Issue store (SQLite, per doc-guid): lifecycle open→resolved(auto on re-check)→orphaned(uid miss).
- P10.4 Async run via JobManager with progress.
- **Tests:** seeded-defect canonical model → golden findings file byte-diffed in CI.
- **Acceptance/DoD:** one-click health check < 2 min on canonical model; findings clickable (uid list). **Risk:** rule quality = product reputation — every core rule reviewed by Sam against real-project intuition.

## Phase 11 — Façade configurator workflows (W11) — post-MVP flagship
**Epic:** the differentiator demo. **Owner:** Rhino/Grasshopper + Semantic BIM Data + Revit API. **Files:** `modules/facade_configurator/**`, `packages/rhino-bridge-addin/**`, adaptive family templates in `fixtures/families/`. **Deps:** P6, P9; Rhino bridge exists.
- P11.1 Zone spec exporter: GH definition + `rhino_run_python` script emitting `amb.facade_zone/1` (promote `scratch/glass_diamond.py` conventions — gpt/cc, counts_expected).
- P11.2 `facade_apply_zone`: spec → type mapping → adaptive placement plan (batch `revit_place_family_instance` or new batched C# command if perf demands).
- P11.3 Variant management: spec-hash variants, re-apply as diff (update/create/delete itemized).
- P11.4 Preview lane: DirectShape with PREVIEW marker + auto-cleanup, behind explicit user opt-in.
- **BIM concepts:** adaptive components, curtain systems, family loading, panel count reconciliation (no silent skips).
- **Tests:** 1476-panel golden case — Rhino count == plan count == placed count == mapping rows.
- **Acceptance/DoD:** tune-in-Rhino → approve variant → native panels in Revit → re-tune → diff-apply. **Risks:** placement perf (batch command likely needed — measure at 500 panels first), family availability UX.

## Phase 12 — Rhino.Inside.Revit / Grasshopper bridge (W12, W13-GH)
**Epic:** meet computational designers in-process. **Owner:** Rhino/Grasshopper. **Deps:** P11.
- P12.1 GH components (`AMB Connect`, `AMB Snapshot`, `AMB Zone Out`, `AMB Plan Preview`) wrapping hub HTTP.
- P12.2 RiR exemplar definition + supported version matrix doc.
- P12.3 Rhino bridge hardening: Contract v2 (dynamic port + token) replacing hardcoded :3004.
- **Tests:** exemplar runs scripted; version matrix manually checklisted per release.
- **Acceptance/DoD:** W12 story demo; no write path bypasses gate. **Risk:** RiR/Rhino/Revit version triangle — pin and document, don't chase.

## Phase 13 — Speckle / IFC / Navisworks bridge (W15)
**Epic:** coordination loop closes. **Owner:** Integration. **Deps:** P4 (Navis registration), P6.
- P13.1 Speckle: snapshot publish/receive (`speckle_publish_version` lane) → delta → reconciliation.
- P13.2 IFC: Revit-vs-IFC comparison report (mapper GlobalId↔UniqueId); `ifc_validate` surfaced in qaqc pack.
- P13.3 Navisworks: clash results → mapper → Revit selection + issue-store import; viewpoint per finding.
- **Tests:** RVT+IFC+NWF fixture triple; mocked Speckle server (exists) + live smoke.
- **Acceptance/DoD:** "show clash #12 in Revit" works; IFC comparison report on fixtures. **Risk:** GUID mapping fidelity across export paths — validate early with the fixture triple.

## Phase 14 — Excel / Power BI / DuckDB reporting (W8, W16)
**Epic:** management-grade outputs. **Owner:** Integration + Report Generator module (Plugin App). **Deps:** P6, P10.
- P14.1 `export_excel` (openpyxl): elements/params/findings workbook + formatted QA summary sheet.
- P14.2 `report_generator` module: templates, destinations (sandboxed), schedule-able via jobs.
- P14.3 Power BI file lane: SQLite (exists) + shipped `.pbit` template; live lane per D-009 (DAX health + `powerbi_execute_dax`).
- P14.4 Parquet mirror + DuckDB queries (P2 priority — can slip).
- **Tests:** golden workbook diff; `.pbit` refresh smoke (manual checklist); SQLite↔Parquet row parity.
- **Acceptance/DoD:** W8 demo: health check → Excel + PBI dashboard refresh. **Risk:** schema evolution — `schema_version` column enforced from first export.

## Phase 15 — AI agent orchestration
**Epic:** multi-step, multi-app recipes (roadmap Phase C, scoped down). **Owner:** MCP Tooling + Product Architect. **Deps:** P10, P13.
- P15.1 Recipe format (YAML: steps = tool calls with arg templating + conditionals) + run records.
- P15.2 `recipe_run/status/list` tools; recipes respect the gate (mutating steps produce plans).
- P15.3 Three shipped recipes: nightly-health-check→Excel; export→clash→issue-import; snapshot→Speckle publish.
- P15.4 `agent_reviewer` module (P2): second-model review of pending plans.
- **Acceptance/DoD:** the three recipes run end-to-end. **Risk:** building a workflow engine — keep it linear steps + conditionals, no DAG until pulled.

## Phase 16 — UI/UX & plugin command surface
**Epic:** the product face (runs parallel from P5 behind endpoint contracts). **Owner:** UI/UX + Revit API (pane host). **Files:** `packages/revit-bridge-addin/src/UI/**`, `panel/**`. **Deps:** P2 ADR-0011; integrates against P4/P5/P7/P10 endpoints.
- P16.1 Dockable pane host (`IDockablePaneProvider` + WebView2 + message bridge).
- P16.2 Panel app: chat view, plan cards (approve/reject/approve-similar), findings tab, run log (audit tail), settings.
- P16.3 Ribbon: 5 product commands (Open Panel, Health Check, Pending Actions, Reports, Settings); keep existing Connection panel.
- P16.4 Empty/error states: hub down, no doc, stale snapshot, offline LLM.
- **Tests:** panel↔hub contract tests (endpoint fixtures); manual UX checklist per release; WebView2 runtime absence fallback message.
- **Acceptance/DoD:** the W7+W5 stories fully driven from the panel by a non-programmer. **Risks:** WebView2 in Revit process (memory, load order — spike first in P16.1); UI scope creep (card set is fixed for MVP).

## Phase 17 — Testing & sample models
**Epic:** trust through goldens. **Owner:** Testing (starts Wave 1 — the model script is a P3 dependency!). **Files:** `fixtures/**`, `tests/e2e/**`, `.github/workflows/**`.
- P17.1 Canonical test model **generator script** (idempotent: builds the RVT via bridge tools — levels, 200 walls, doors/windows, rooms incl. seeded defects, views/sheets, groups, families). Script, not binary, so it's diffable and per-version buildable.
- P17.2 Seeded-defect register (which rule catches what) → golden findings.
- P17.3 e2e harness extending `test_e2e.py`: hub+add-in round trip, gate paths, snapshot goldens.
- P17.4 CI: pytest+ruff; dotnet matrix net48/net8 (Nice3point NuGet); doc link check; e2e nightly on self-hosted runner with Revit (or scripted local `make e2e` if no runner). ⚠ decide runner story (D-012).
- **Acceptance/DoD:** every MVP workflow has a golden; CI green gate on PRs. **Risk:** Revit-in-CI licensing → local scripted fallback documented.

## Phase 18 — Documentation & tutorials
**Epic:** docs a firm can adopt from. **Owner:** Documentation. **Deps:** MVP features stable.
- P18.1 MkDocs site (roadmap Phase F): install, quickstart, workflows (one page per W#), module authoring, tool reference (generated), security model.
- P18.2 Three tutorials: "Ask your model", "Health check + fix", "Batch parameters from Excel".
- P18.3 Video/demo script for the flagship demo (P11).
- **Acceptance/DoD:** cold-start user completes tutorial 1 in <15 min without help.

## Phase 19 — Packaging, installer, release
**Epic:** double-click install. **Owner:** Release (+ Security for signing). **Deps:** P16.
- P19.1 Add-in installer (WiX/Inno): `.addin` + multi-target DLLs into per-version folders; WebView2 runtime bootstrap.
- P19.2 Hub packaging decision D-010 (pipx vs bundled runtime) implemented; `server.json`/marketplace listings updated (`docs/marketplaces.md`).
- P19.3 Release pipeline: tag → build matrix → DLL license scan (exists) → artifacts → CHANGELOG cut. Code-signing cert acquisition. ⚠ human: signing + publishing.
- **Acceptance/DoD:** clean Windows machine → installer → tutorial 1 works. **Risk:** unsigned binaries = SmartScreen friction (budget for cert).

## Phase 20 — Enterprise readiness
**Epic:** what firms ask before rollout. **Owner:** Security/Safety + Release.
- P20.1 Central config (firm-managed settings file: approval_mode lockdown, module allowlist, telemetry off switch).
- P20.2 Audit-ledger export + retention policy; threat model doc refresh.
- P20.3 Workshared/BIM360 model behavior matrix (ownership, sync etiquette: never `revit_sync_to_central` without explicit plan).
- P20.4 License enforcement for commercial modules (open-core seam — mechanism only, pricing stays private).
- **Acceptance/DoD:** enterprise checklist doc answerable "yes" line-by-line.

## Phase 21 — Future roadmap
**Epic:** parked, explicitly. **Owner:** Product Architect. Contents: remote MCP/REST facade (roadmap H), BYO-LLM guides, Dynamo package (W13-D), APS Issues at scale, MS Graph, additional switches (Archicad/Tekla — roadmap G), marketplace, IDS full support, BCF. Each graduates only via a `DECISIONS_AND_RISKS.md` entry with a pull signal (user request, revenue, demo need).

---

## Dependency spine

```
P0 → P1 → P2 ─┬→ P3 (C#) ──┐
              ├→ P4 (hub) ─┼→ P5 → P6 → P7 → P8 → P9 → P10 ─┬→ P11 → P12
              └→ P17.1 ────┘         (P16 UI parallel from P5)├→ P13 → P15
                                                              └→ P14
P16+P17+P18 → P19 → P20        P21 parked
```
