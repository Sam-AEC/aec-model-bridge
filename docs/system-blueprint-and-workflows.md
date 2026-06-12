# AEC Omni-Bridge — System Blueprint & Workflows

**Status:** Canonical architecture document (v1.0, 2026-06-12)
**Owner:** A. Sam Mohammad (Sam-AEC)
**Scope:** This is the master blueprint referenced by `docs/agent-handover-prompt.md`. It defines the target architecture of the Omni-Bridge ecosystem, the flagship cross-platform workflows, the modular distribution model, and the full scaffolding plan. It supersedes the workflow sections of `docs/proposed-multi-workflow-architecture.md` and extends `docs/0001-multi-provider-architecture.md` (ADR 0001) without contradicting it.

**Naming convention used throughout:**
- **AEC Model Bridge** — the product name (PyPI package, add-ins, MCP registry entry).
- **Omni-Bridge** — the orchestration layer inside the hub: the component that composes multiple switches into end-to-end pipelines.
- **Switch** — a native adapter for one platform (Revit add-in, Navisworks add-in, Speckle module, etc.). Each switch is installed independently.

---

## 0. Verified Baseline (what is actually true on 2026-06-12)

A blueprint built on inaccurate claims produces broken plans. This table is the audited ground truth, verified against the repository — future agents should trust this section over older handover language.

| Component | Claimed elsewhere | Verified state |
| --- | --- | --- |
| Revit switch (`packages/revit-bridge-addin`) | Fully operational | **True.** ~103 routes on `127.0.0.1:3000`, ExternalEvent threading, multi-target 2024–2027, IronPython escape hatch. |
| Python hub (`packages/mcp-server-revit`) | 100 tools | **True and more.** ~155 tools across 9 registered providers (Revit, IFC, mapper, exporter, jobs, Rhino.Compute, graph, Speckle OAuth, Autodesk). |
| Navisworks switch (`packages/navisworks-bridge-addin`) | "Fully operational clash execution" | **Stub.** `/health` works; `/execute` returns only document title/filename/model count. No clash routes. No `NavisworksProvider` registered on the Python side. |
| Rhino switch | "Active MCP provider on :9876" | **Partial.** `RhinoProvider` targets Rhino.Compute (default `https://localhost:5001`). `McpProxyProvider` (SSE proxy for a live Rhino MCP at :9876) exists but is **not registered** and has a connect-lifecycle bug (`_connect()` is never invoked). |
| Speckle switch | Specklepy V3 module | **Duplicated.** `providers/cloud.py` (14 OAuth/GraphQL tools, registered) coexists with orphaned `providers/speckle.py` (2 tools, unregistered, conflates model name with model ID, error-as-string returns). `pyproject.toml` pins `specklepy>=2.17.0`, which permits an incompatible 2.x install. |
| `scratch/orchestrate_all.py` | "Review first" | **Never existed.** The end-to-end pipeline has no implementation. This blueprint defines what replaces it (§6, §10 Phase C). |
| Local bridge security | — | Loopback-only but **unauthenticated**; ports hardcoded (3000, 3002). ADR 0001 §5 (per-session bearer tokens, dynamic ports) is not yet implemented. |
| `docs/security.md` config keys (`allow_destructive`, `allowed_tools`) | Documented | **Not implemented** in `config.py` or enforced anywhere. |

---

## 1. Why Omni-Bridge Exists — the Pains It Removes

The AEC industry pays an **interoperability tax**: BIM professionals routinely spend a third or more of their time on data logistics rather than design or coordination. The specific, recurring pains this ecosystem targets:

1. **Concept-to-BIM re-modeling.** Computational designers iterate massing in Rhino/Grasshopper, then someone rebuilds it manually in Revit for documentation. Geometry, levels, and parameters are re-keyed by hand; design intent is lost at every handoff.
2. **Clash coordination as a manual ritual.** VDC leads append models in Navisworks, run Clash Detective by hand, screenshot results into PDFs or BCF, and discuss them in weekly meetings. Clash status is never live; by meeting time the models have changed.
3. **Stale dashboards.** Model data reaches Power BI via fragile exports: someone runs a Dynamo graph or schedule export, saves an Excel file to a network drive, and refreshes a dataset. When that person is on holiday, the dashboard lies.
4. **Compliance checking by eyeball.** Naming conventions, parameter completeness (COBie, employer information requirements, IDS specifications) are spot-checked manually before milestones, which means they are checked rarely and inconsistently.
5. **Tribal-script fragility.** Every firm accumulates in-house Dynamo/pyRevit scripts that are machine-bound, undocumented, and die when their author leaves. There is no standard runtime for AEC automation.
6. **AI lockout.** LLM agents cannot operate desktop BIM software. The Model Context Protocol changes this — but only if someone ships the runtime that exposes Revit, Navisworks, Rhino, and the CDEs as safe, structured tools. That runtime is this project.

**The thesis:** Omni-Bridge is the *agentic control plane* for the AEC software stack — one secure MCP runtime, many independently installable switches, with the orchestration intelligence (identity translation, semantic graph, workflow recipes, provenance) living in the hub rather than in any single vendor's tool.

---

## 2. Target Architecture — Layered Hub & Spoke

```text
┌───────────────────────────────────────────────────────────────────────┐
│ LAYER 0 — AGENTS & CLIENTS                                            │
│   Claude Desktop · VS Code / Copilot · custom agents · CI pipelines   │
└───────────────────────────────┬───────────────────────────────────────┘
                                │ MCP (stdio / SSE)
┌───────────────────────────────▼───────────────────────────────────────┐
│ LAYER 1 — THE HUB (Python: aec-model-bridge)                          │
│                                                                       │
│  ┌─────────────────────────  Omni-Bridge Orchestrator  ─────────────┐ │
│  │  Workflow recipes · run manifests (provenance) · fallback logic  │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │
│  │ Provider     │ │ Identity     │ │ Semantic     │ │ Async Job    │ │
│  │ Registry +   │ │ Translation  │ │ Graph Engine │ │ Pipeline     │ │
│  │ Discovery    │ │ Registry     │ │ (networkx)   │ │ (JobManager) │ │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘ │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │ Policy & Audit: workspace sandbox · redaction · mutation gates   │ │
│  └───────────────────────────────────────────────────────────────────┘ │
└──────┬──────────────┬──────────────┬──────────────┬──────────────┬────┘
       │ loopback HTTP│ loopback HTTP│ in-process   │ HTTPS OAuth  │ HTTP jobs
┌──────▼─────┐ ┌──────▼─────┐ ┌──────▼─────┐ ┌──────▼─────┐ ┌──────▼─────┐
│ LAYER 2 —  │ │            │ │            │ │            │ │            │
│ DESKTOP    │ │ DESKTOP    │ │ HEADLESS   │ │ CLOUD      │ │ COMPUTE    │
│ SWITCHES   │ │ SWITCHES   │ │ SWITCHES   │ │ SWITCHES   │ │ SWITCHES   │
│            │ │            │ │            │ │            │ │            │
│ Revit      │ │ Navisworks │ │ IfcOpen-   │ │ Speckle    │ │ Rhino.     │
│ :3000*     │ │ :3002*     │ │ Shell      │ │ APS (ACC/  │ │ Compute    │
│ Rhino live │ │ Solibri    │ │ openNURBS  │ │ Forma)     │ │ APS Design │
│ (:9876)    │ │ (future)   │ │ Excel/xlsx │ │ MS Graph   │ │ Automation │
│            │ │            │ │ DuckDB     │ │ (future)   │ │ (future)   │
└────────────┘ └────────────┘ └────────────┘ └─────┬──────┘ └────────────┘
   * dynamic ports + per-session tokens (Switch Contract v2, §3)
                                                    │
┌───────────────────────────────────────────────────▼───────────────────┐
│ LAYER 3 — DATA PLANE                                                  │
│  Speckle projects (cloud CDE / data lake)  ·  Local Parquet/DuckDB    │
│  lakehouse  →  Power BI (Speckle connector or direct Parquet import)  │
└───────────────────────────────────────────────────────────────────────┘
```

### Core architectural rules

1. **Switches never call each other.** All cross-platform composition happens in the Orchestrator. A switch is a thin translator around one vendor API (ADR 0001 consequence — preserved).
2. **The hub never assumes a switch is installed.** Every workflow declares the capabilities it needs and the hub resolves them at run time against live discovery state (§4). Missing switches produce graceful degradation or a precise, actionable error ("Navisworks switch not detected — install from <release URL> or rerun with `clash_engine: graph`").
3. **Manifests are the single source of truth.** Tool catalogs, docs, and client-facing tool lists are generated from provider capability manifests — never hand-maintained in parallel (kills the `docs/tools.md` staleness class of bug permanently).
4. **Native identity is preserved; translation is explicit.** The Identity Translation Registry maps IFC GlobalId ↔ Revit UniqueId ↔ Rhino UUID ↔ Speckle ObjectId ↔ Navisworks item paths. No universal BIM object model is attempted (ADR 0001 §4 — preserved).
5. **Everything long-running is a job.** Any step that can exceed ~2 s returns a `JobReference`; workflows are jobs composed of jobs.
6. **Every pipeline run leaves a provenance record.** See §5.2 — this is the "unified JSON object" of the original handover prompt, formalized.

---

## 3. Switch Contract v2 (the standardized spoke interface)

Every desktop switch — current and future — implements the same minimal local contract. This is what makes the ecosystem modular: the hub speaks one dialect to all of them.

### 3.1 Endpoints

```text
GET  /health          → { status, application, host_version, connector_version,
                          protocol_version, document: {...} | null }
GET  /capabilities    → capability manifest (ADR 0001 §3 schema):
                        tools[] with name, input/output JSON schema,
                        is_mutating, confirmation_required, execution_mode
POST /execute         → { tool, payload, request_id, idempotency_key? }
                        → result envelope (below)
```

### 3.2 Result envelope (uniform across all switches)

```json
{
  "ok": true,
  "request_id": "…",
  "data": { },
  "warnings": [],
  "artifacts": [ { "kind": "file|url|object_ref", "value": "…" } ],
  "job": null
}
```

### 3.3 Security and discovery (implements ADR 0001 §1/§5 — currently missing)

- **Dynamic loopback ports.** No more hardcoded 3000/3002 collisions when two hosts run at once. Each switch binds an OS-assigned loopback port at startup.
- **File-based local discovery registry.** On startup each switch writes `%LOCALAPPDATA%\AECModelBridge\registry\<provider>-<pid>.json` containing: provider id, endpoint, PID, host version, connector version, capability digest, session token, started-at timestamp. On shutdown it deletes the file. The hub scans this directory, validates PIDs are alive, and prunes stale entries. (File-based discovery is chosen over a daemon or mDNS: zero extra processes, trivially debuggable, Windows-native.)
- **Per-session bearer token.** Generated by the switch at startup, published only via the registry file (user-readable only via ACL), required on every `/execute`. The hub reads it from the registry file; tokens never enter MCP arguments, results, or logs.
- **Limits.** Request size caps, per-switch concurrency limits, protocol-version rejection of stale clients.
- **Back-compat window.** The hub continues to probe legacy fixed ports (3000/3002, no token) for one minor release, logging a deprecation warning, so existing installs don't break the day Contract v2 ships.

### 3.4 What stays out of the generic contract

Reflection, arbitrary method invocation, and script execution (`execute_python`) remain **Revit-only, high-risk, explicitly enabled** capabilities. They are flagged `high_risk: true` in the manifest and gated by the policy layer (§5.4). They are never generalized to other switches.

---

## 4. Modular Distribution — install only what you use

This is a first-class product requirement, not an afterthought: **the user installs individual switches for the software they own; the hub orchestrates whatever it finds.**

### 4.1 Distribution units

| Unit | Channel | Contains |
| --- | --- | --- |
| Hub (`aec-model-bridge`) | PyPI + `.mcpb` bundle + MCP Registry | Python MCP server, all headless switches (IFC, exporter, graph, mapper, jobs), cloud switch clients (Speckle, APS), orchestrator |
| Revit switch | GitHub release zip per Revit year (2024–2027), later Autodesk App Store | Add-in DLLs + manifest |
| Navisworks switch | GitHub release zip per year | Add-in DLLs + manifest |
| Rhino live switch (future) | Food4Rhino + GitHub release | Rhino plugin (.rhp) |
| Solibri switch (future) | GitHub release | Java Open API plugin or REST automation profile |
| Workflow recipe packs | Bundled with hub + downloadable recipe files | YAML/JSON recipes (§5.1) |

Headless and cloud switches ship inside the hub because they have no native binary; desktop switches always ship separately because they are version-locked to host software the user may not own.

### 4.2 The zero-switch experience (the trial funnel)

The hub must be fully demonstrable with **no desktop software installed**: mock mode + the IFC provider + a sample IFC file + the semantic graph + a local Parquet export gives a complete "audit an IFC and build a dashboard" experience on any machine. This is deliberately the first-run tutorial — it removes every licensing barrier between a curious BIM manager and a working demo.

### 4.3 Presence-aware behavior

- `aec_bridge_status` (new hub tool): reports every known switch — installed/alive/version/capability digest — and what each missing switch would unlock. This single tool is the diagnostic entry point for users and agents alike.
- Workflows declare `requires: [capabilities…]` and optional `fallbacks:`. The orchestrator resolves these against live discovery before starting, and reports precisely which step will degrade and why.
- A future `aec-bridge doctor` CLI subcommand wraps the same check for humans outside an MCP client (Phase B scaffolding, §10).

### 4.4 Version compatibility policy

- The bridge protocol is versioned independently of product versions (`protocol_version: 2`).
- Hub ↔ switch compatibility is **N / N−1**: the hub supports the current and previous protocol major version.
- The hub warns (never silently fails) on manifest digest or protocol mismatches, with the exact download URL for the matching switch release.

---

## 5. Hub Internals — the Omni-Bridge Orchestrator

The orchestrator is the one genuinely new architectural component this blueprint introduces. Everything else hardens what already exists.

### 5.1 Workflow recipes (declarative, not scripted)

The original plan ("write `scratch/orchestrate_all.py`") couples pipelines to code. Instead, pipelines are **data**: versioned recipe documents executed by a generic engine.

```yaml
# recipes/concept-to-dashboard.yaml  (illustrative schema, finalized in Phase C)
recipe: concept_to_dashboard
version: 1
description: Rhino massing → Revit elements → clash check → data lake → dashboard
requires:
  - rhino.read_geometry          # capability names, not provider names
  - revit.create_elements
  - revit.read_quantities
clash:
  prefer: navisworks.run_clash_test
  fallback: graph.audit_clashes   # AABB clash on the semantic graph
publish:
  prefer: speckle.publish_version
  also: exporter.to_parquet       # local lakehouse copy, always
steps:
  - id: extract_massing
    tool: rhino_query_geometry
    output: massing
  - id: instantiate
    tool: revit_create_elements_batch
    input: { geometry: $massing }
    mutating: true
    confirmation: required
    idempotency_key: $run_id
  - id: quantities
    tool: revit_get_quantities
    input: { elements: $instantiate.created }
  - id: clash
    capability: clash             # resolved via prefer/fallback above
    input: { scope: $instantiate.created }
  - id: package
    tool: orchestrator_build_run_record
  - id: publish
    capability: publish
    input: { record: $package.record }
```

Why declarative wins here: recipes are diffable, shareable, and sellable (recipe packs become a product surface, see strategy doc); the engine enforces confirmation gates and idempotency uniformly; and an agent can *read* a recipe to explain a pipeline before running it.

Exposed MCP tools: `workflow_list`, `workflow_describe`, `workflow_run` (returns a `JobReference`), `workflow_status`, `workflow_cancel`. Each step execution flows through the existing `JobManager`.

### 5.2 The Run Record (provenance — the "unified JSON object")

Every workflow run emits exactly one Run Record, which is both the Speckle-committed payload and the audit artifact:

```json
{
  "run_id": "run_2026-06-12T14-03_concept_to_dashboard_01",
  "recipe": { "name": "concept_to_dashboard", "version": 1 },
  "started_at": "…", "finished_at": "…", "status": "succeeded",
  "switches": { "revit": { "host": "2026", "connector": "1.2.0" }, "...": {} },
  "inputs":  { "rhino_geometry": { "object_count": 42, "source": "…" } },
  "outputs": {
    "revit_elements": [ { "unique_id": "…", "ifc_guid": "…", "volume_m3": 12.4 } ],
    "clashes": [ { "test": "STR-vs-MEP", "status": "new", "item_a": {}, "item_b": {} } ],
    "quantities": { "total_volume_m3": 1024.6, "by_category": {} }
  },
  "identity_map": [ { "ifc_guid": "…", "revit_unique_id": "…", "rhino_uuid": "…",
                      "speckle_object_id": "…" } ],
  "degradations": [ "navisworks offline — clash via graph.audit_clashes" ],
  "artifacts": [ { "kind": "url", "value": "https://app.speckle.systems/…" },
                 { "kind": "file", "value": "<workspace>/lake/run_…parquet" } ]
}
```

The Run Record schema is versioned and published — it is the contract Power BI dashboards are built against, which means dashboards survive switch/recipe changes.

### 5.3 Identity, graph, jobs (existing components — roles confirmed)

- **Identity Translation Registry** (`identity_mapper.py`): persisted per-workspace (move from in-memory dict to SQLite via the existing exporter); populated automatically by mutating workflow steps (e.g., `revit_create_elements_batch` registers Rhino UUID → Revit UniqueId mappings as it creates).
- **Semantic Graph Engine** (`graph.py`): compiled on demand from IFC/Revit data; serves as the clash and audit fallback engine; gains Parquet/GraphML export targets (already on the strategic roadmap).
- **Async Job Pipeline** (`jobs.py`): unchanged conceptually; gains MCP progress notifications so agents see step-level workflow progress instead of polling.

### 5.4 Policy layer (close the documented-but-unimplemented gap)

Implement what `docs/security.md` already promises: `allowed_tools` allow-list, `allow_destructive` + `destructive_confirm` gates, enforced in one place (the registry's execute path) so every provider inherits them. High-risk tools (reflection/scripting) require an explicit opt-in config flag *and* per-call confirmation.

---

## 6. Flagship Workflows (the five proof pipelines)

These are the demonstrations that define the product publicly. Each lists required capabilities, fallback behavior, and acceptance criteria. Together they replace the never-written `scratch/orchestrate_all.py` with something durable.

### W1 — Concept-to-BIM (Rhino → Revit)
*The computational designer's handoff, automated.*
- **Flow:** Pull massing/coordinate matrices from the Rhino switch (live plugin via proxy, or Rhino.Compute) → batch-instantiate walls/floors/columns/levels in Revit → read back volumes, areas, type costs.
- **Requires:** `rhino.read_geometry`, `revit.create_elements`, `revit.read_quantities`.
- **Fallback:** No live Rhino → accept a `.3dm` path via openNURBS headless read (future) or a pre-exported JSON coordinate file.
- **Accepts when:** A sample Grasshopper massing becomes ≥3 Revit categories of real elements with correct levels, and quantities round-trip into the Run Record. Demo runtime under 2 minutes.

### W2 — Coordination Loop (Revit/IFC → Navisworks → BCF-ready output)
*Clash detection as a callable function instead of a meeting.*
- **Flow:** Append/refresh models in Navisworks → select or create a clash test → run Clash Detective → retrieve grouped results with item identities → translate clash item IDs back to Revit UniqueIds/IFC GUIDs via the Identity Registry.
- **Requires:** `navisworks.run_clash_test` (Phase B deliverable), `mapper.translate_id`.
- **Fallback:** `graph.audit_clashes` (AABB on the semantic graph) with an explicit "approximate engine" degradation note in the Run Record.
- **Accepts when:** A two-model clash test runs end-to-end from one MCP call and every clash row carries a resolvable Revit element reference.

### W3 — Model Health & Compliance Audit (IFC + IDS + graph)
*The BIM manager's milestone checklist, continuous.*
- **Flow:** Open IFC → run IDS specification checks (strategic roadmap item, lands in `IfcProvider`) → run graph audits (disconnected systems, unsupported load paths, naming/parameter completeness) → emit a scored model-health Run Record.
- **Requires:** `ifc.*` only — **this is the zero-switch demo** (§4.2).
- **Accepts when:** A public sample IFC produces a health score with itemized findings, fully offline, on a machine with no Autodesk products.

### W4 — Data-Lake Drop (everything → Speckle + Parquet → Power BI)
*Dashboards that are never stale.*
- **Flow:** Take any Run Record → commit as a Speckle version (Power BI's Speckle connector reads it live) → simultaneously write Parquet to the workspace lakehouse for DuckDB/direct Power BI import (the zero-cloud, IP-sensitive variant).
- **Requires:** `speckle.publish_version` *or* `exporter.to_parquet` (either alone is a valid pipeline).
- **Accepts when:** One refresh in Power BI shows new clash counts/quantities within a minute of a workflow finishing, via both the cloud path and the local path; ships with two starter `.pbit` template files.

### W5 — 5D/QTO Handoff (Revit → Excel)
*Meet the cost team where they live.*
- **Flow:** Extract schedules/quantities from Revit → write to structured Excel tables (local `.xlsx` via headless switch first; Microsoft Graph/SharePoint live workbooks in Wave 2) → optionally read back cost rates entered by estimators and write them into Revit parameters (the round-trip that firms currently script per-project).
- **Requires:** `revit.read_schedules`, `excel.write_table` (Wave 2 switch).
- **Accepts when:** A schedule lands as a formatted Excel table and an edited rate column flows back into a Revit shared parameter with a dry-run diff shown first.

---

## 7. Data Plane

Two lake targets, deliberately both:

1. **Speckle as cloud CDE/lake** — already integrated (OAuth PKCE, 14 tools). Run Records and element payloads commit as versions; Power BI consumes via the Speckle connector; webhooks (strategic roadmap) trigger downstream automation. Best for teams, sharing, live dashboards.
2. **Local Parquet/DuckDB lakehouse** — the strategic roadmap's `aec_export_to_parquet`, elevated to a standard workflow output. Best for firms that will not put model IP in a cloud, and for offline demos. DuckDB enables SQL over runs ("clash count trend across the last 20 runs") with zero infrastructure.

The Run Record schema (§5.2) is the stable contract for both. Dashboard templates target the schema, not the tools.

---

## 8. Expansion Roadmap — switch waves

Integration order rebalanced from `docs/integration-expansion-handover.md` to elevate the tools BIM professionals touch daily (Excel, ACC/Forma, Solibri) above strategically interesting but rarer platforms.

### Wave 1 (now — Phases A–D in §10): make the existing four switches true
Revit (done) · Navisworks (complete the stub) · Rhino (register + fix the proxy; keep Rhino.Compute as the compute variant) · Speckle (consolidate to one provider) · plus the Orchestrator and Data Plane.

### Wave 2 (next two quarters): the everyday-tools wave

| Switch | Type | Approach | First useful release |
| --- | --- | --- | --- |
| **Excel** | Headless first, cloud second | Local `.xlsx` read/write in-hub (no auth, works on network drives — matches how firms actually operate); Microsoft Graph for SharePoint/OneDrive live workbooks as the follow-up | W5 round-trip: schedules out, cost rates back in |
| **ACC / Forma (APS)** | Cloud | `AutodeskDataProvider` already has 12 tools and APS OAuth — finish and harden: project/file discovery, AEC Data Model GraphQL reads, Issues (clash publishing target), then Data Exchange | Publish W2 clash results as ACC Issues; pull ACC-hosted models into W3 audits |
| **Solibri** | Desktop | Solibri Office exposes local automation (Solibri Open API / REST automation as used by Autorun). Two-track: (a) drive checking runs and BCF export via the local interface where licensing permits; (b) file-level fallback — feed Solibri with IFC, consume its BCF/Excel outputs into Run Records. **Verify current Solibri API terms before building** (licensing note below) | W3 extended: "run Solibri ruleset, merge findings into the model-health score" |

### Wave 3 (opportunity-driven): Tekla, Archicad, iTwin, Trimble Connect, Procore, P6, SketchUp — per the priority analysis and API notes already in `docs/integration-expansion-handover.md`. Each must earn its place with a named workflow and test access before any package is created.

### Licensing boundary (applies to every Wave 2/3 desktop switch)
The GPL Revit Linking Exception covers **Revit only**. Before distributing Navisworks (already shipped — review retroactively), Solibri, Rhino, or Tekla switches: review vendor SDK/marketplace terms, keep proprietary SDK binaries out of the repo, and obtain qualified legal review for either per-connector exceptions or a generalized host-application linking exception. This is tracked as a Phase A task, not deferred indefinitely.

---

## 9. Hardening Backlog (defects and drift found in the 2026-06-12 audit)

Ordered by risk. These precede all new features (Phase A).

1. **Speckle consolidation:** delete or fold `providers/speckle.py` into `cloud.py`; fix `specklepy` pin to `>=3,<4`; fix model-name-as-ID conflation; raise exceptions instead of returning error strings.
2. **Proxy provider:** register `McpProxyProvider`, fix the never-called `_connect()` lifecycle, add reconnect handling, document the `:9876` Rhino MCP pairing in the README accurately.
3. **Local auth:** implement Switch Contract v2 tokens + discovery registry (§3.3) in hub, Revit switch, and Navisworks switch.
4. **Policy gap:** implement `allowed_tools` / `allow_destructive` / `destructive_confirm` so `docs/security.md` stops describing fiction.
5. **Docs drift:** generate the tool catalog from manifests; fix the "25 tools" claim in `docs/architecture.md`; document all 9 providers' tools.
6. **Repo hygiene:** remove `docs/Untitled.3dm` + `.rhl`; exclude `packages/*/build/` and `.venv` from the tree; verify `dist/` artifacts belong in releases, not git.
7. **Tests:** contract tests run against every registered provider (the `FakeProvider` harness exists — extend it); add IFC-provider and proxy-provider test files; add a mock-mode end-to-end workflow test per flagship recipe.

---

## 10. Scaffolding Plan — phases, epics, definitions of done

No code in this document by design; every task below names its deliverable and its done-condition so any implementing agent (or future you) can execute without re-deriving intent.

### Phase A — Truth & Hygiene (≈ 2 weeks)
| # | Task | Done when |
| --- | --- | --- |
| A1 | Execute hardening backlog items 1, 2, 5, 6 (§9) | One Speckle provider; proxy registered and connecting; docs regenerated; repo clean; CI green |
| A2 | Update `docs/agent-handover-prompt.md` to point at this blueprint and reflect §0 | No doc references a non-existent file or overstates switch status |
| A3 | Licensing review ticket for Navisworks/Rhino/Solibri switches (§8) | Written legal position recorded in `LICENSING.md` or a new exception file |
| A4 | Provider contract tests extended to all 9 providers | `pytest` contract suite parameterized over the registry passes |

### Phase B — Switch Contract v2 + Navisworks completion (≈ 4 weeks)
| # | Task | Done when |
| --- | --- | --- |
| B1 | Discovery registry + per-session tokens + dynamic ports in hub | Hub resolves switches from `%LOCALAPPDATA%` registry files; legacy fixed-port probe behind deprecation warning |
| B2 | Revit switch: Contract v2 (token, registry file, `/capabilities` manifest generation) | `aec_bridge_status` shows Revit with capability digest; unauthorized `/execute` rejected |
| B3 | Navisworks switch: real command routing — model tree, append/refresh, saved viewpoints, clash test list/run/results (grouped, with item identities) | W2 runs end-to-end against a live Navisworks Manage session |
| B4 | `NavisworksProvider` in the hub + tools + tests | Navisworks tools appear in MCP `list_tools`; mock-mode tests pass without Navisworks installed |
| B5 | `aec_bridge_status` hub tool + `aec-bridge doctor` CLI | Both report installed/alive/missing switches with actionable install pointers |
| B6 | Policy layer (backlog item 4) | Destructive call without opt-in is refused with a clear message; allow-list enforced; security tests added |

### Phase C — Omni-Bridge Orchestrator (≈ 4 weeks)
| # | Task | Done when |
| --- | --- | --- |
| C1 | Recipe schema (finalize §5.1), engine design ADR (ADR 0002) | ADR merged; schema versioned and validated with Pydantic |
| C2 | Workflow engine on the job pipeline: capability resolution, fallbacks, confirmation gates, idempotency, MCP progress notifications | `workflow_run` executes a 3-step mock recipe with one forced fallback and one confirmation gate, observable via `workflow_status` |
| C3 | Run Record schema v1 + builder (§5.2) | Schema published in docs; every workflow emits a valid record; identity map auto-populated |
| C4 | Flagship recipes W1–W4 authored and tested in mock mode | All four pass mock-mode e2e tests in CI |
| C5 | Live verification: W1 (Rhino+Revit), W2 (Navisworks), W3 (IFC only), W4 (Speckle + Parquet) | Each demonstrated against real hosts; recorded results (versions, dates, gaps) appended to this doc |
| C6 | Persist Identity Registry to SQLite per workspace | Mappings survive hub restarts; `mapper` tools read/write the store |

### Phase D — Data Plane & Dashboards (≈ 3 weeks)
| # | Task | Done when |
| --- | --- | --- |
| D1 | Parquet/DuckDB exporter as a standard workflow output (strategic roadmap item 1) | W4 local path produces Parquet readable by DuckDB and Power BI |
| D2 | Two Power BI templates (`.pbit`): Model Health (W3) and Coordination (W2) against Run Record schema | A user with only the templates and one Run Record gets a working dashboard in <10 minutes |
| D3 | IDS rule checking in `IfcProvider` (strategic roadmap item 2) | W3 includes IDS findings; sample IDS files in fixtures |
| D4 | Webhook notifications on job/workflow completion (strategic roadmap item 3) | Teams/Slack Adaptive Card posts on W2 completion in a live test |

### Phase E — Wave 2 switches (≈ 6 weeks, parallelizable)
| # | Task | Done when |
| --- | --- | --- |
| E1 | Excel headless switch + W5 recipe | W5 acceptance met (round-trip with dry-run diff) |
| E2 | ACC/Forma hardening: AEC Data Model reads, Issues publishing from W2 | Clash results appear as ACC Issues in a live project |
| E3 | Solibri integration spike (API access, licensing, approach decision ADR) | ADR 0003 records the chosen track (API vs file exchange) with evidence |
| E4 | Solibri switch per ADR 0003 + W3 extension | Solibri findings merge into the model-health Run Record |

### Standing engineering practices (all phases)
- One ADR per architectural decision; this blueprint is amended, never silently contradicted.
- Mock-first development: every feature testable in CI without licensed software; live tests behind explicit flags with version/date evidence recorded.
- Conventional commits, semantic versioning, protocol version bumped only via ADR.
- Generated docs over written docs wherever a manifest exists.
- Redaction tests for every new provider (tokens/paths never in tool output).

---

## 11. Open Decisions (tracked, not blocking)

| # | Decision | Leaning | Decide by |
| --- | --- | --- | --- |
| OD1 | Recipe format: YAML vs JSON vs both | YAML authoring, JSON wire | Phase C1 |
| OD2 | Rhino live switch: ship our own .rhp vs document pairing with existing Rhino MCP servers via proxy | Proxy-first (zero maintenance), own plugin only if proxy proves limiting | Phase C5 |
| OD3 | Identity store: SQLite per workspace vs DuckDB unified with lake | SQLite (transactional) with export into lake | Phase C6 |
| OD4 | Hosted control plane (run history UI, scheduled pipelines) — build vs defer | Defer until Wave 2 ships; see strategy doc | Post-E |
| OD5 | Rename repo `Autodesk-Revit-MCP-Server` → product-aligned name (`aec-model-bridge` already used in README clone URL) | Rename with GitHub redirect | Phase A |

---

*Maintained alongside ADR 0001. Amendments require a dated changelog entry below.*

**Changelog**
- 2026-06-12 — v1.0 — Initial blueprint authored; supersedes workflow sections of `proposed-multi-workflow-architecture.md`; baseline audit recorded in §0.
