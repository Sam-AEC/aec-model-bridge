# AEC Model Bridge — Product Vision

> Canonical product name: **AEC Model Bridge** (repo `Sam-AEC/aec-model-bridge`).
> "AEC Omni-Bridge" is legacy internal branding — permitted only as the name of the *multi-app orchestration vision* (Rhino/Navisworks/PowerBI switches), never as the product name. See `DECISIONS_AND_RISKS.md` D-001.

## 1. Product definition

AEC Model Bridge is a **plugin-style AEC productivity platform** that connects live authoring tools (Revit first; Rhino, Navisworks, Power BI as switches) to AI agents through MCP — with **native BIM semantics as the source of truth** and a **human approval layer** between AI intent and model mutation.

Concretely, it is three layers that already partially exist in this repo:

1. **Switches** — thin C# add-ins inside each host app (`packages/revit-bridge-addin`, `rhino-bridge-addin`, `navisworks-bridge-addin`, `powerbi-bridge-tool`) exposing HTTP `/execute` on the host's API thread.
2. **Hub** — the Python MCP server (`packages/mcp-server-revit`, `mcp_server.py`) with a provider registry, ~170 tools, async jobs, identity mapping, semantic graph, and exporters.
3. **Surface** — Claude Code / any MCP client today; a **dockable in-Revit panel with chat, approval queue, and run log** as the MVP product surface for normal Revit users.

## 2. Target users

| Persona | Today's pain | What they get |
|---|---|---|
| **BIM coordinator / manager** (primary MVP) | Repetitive QA, parameter cleanup, sheet drudgery; Dynamo scripts nobody maintains | Ask the model questions, run health checks, approve bulk fixes from a panel — no code |
| **Façade / computational designer** (Sam's own persona) | Rhino→Revit means dumb DirectShapes or manual rebuilds | Semantic roundtrip: GH panel data → native curtain panels/adaptive components |
| **Automation engineer / BIM developer** | Every firm rebuilds the same Revit-API plumbing | Stable MCP tool surface + module SDK; script in Python against a live model |
| **Project engineer / QA lead** | Model quality invisible until clash day | Rule-based validation → issue lists → Excel/Power BI dashboards |

## 3. Core user problems

1. **BIM data is trapped.** Answering "how many fire-rated doors on level 3 lack a rating parameter?" requires a schedule, a filter, and 20 minutes — or a developer.
2. **Automation has a cliff.** Below the cliff: manual clicking. Above it: Dynamo graphs and pyRevit scripts that rot. Nothing in between speaks natural language.
3. **Cross-tool workflows are lossy.** Rhino→Revit, Revit→Navisworks, Revit→Power BI each drop semantics; every firm hand-rolls the glue.
4. **AI can't be trusted with models.** No mainstream tool lets an LLM near a production RVT because there is no approval, audit, or rollback layer. That layer *is* the product.

## 4. Why this matters / why it is different

| Alternative | What it is | Why AEC Model Bridge is different |
|---|---|---|
| **Dynamo** | Visual programming per-task | We are conversational + persistent tooling, not per-task graphs; Dynamo becomes an *integration target* (Phase 12) |
| **pyRevit** | Script framework + toolbar for Python devs | pyRevit serves scripters; we serve non-programmers via AI + approval UI, and expose a *stable machine interface* (MCP) pyRevit lacks |
| **Speckle** | Data platform / versioned object transport | Speckle moves data between apps; we *act* inside apps. Speckle is one of our transports (17 `speckle_*` tools already exist) |
| **Rhino.Inside.Revit** | Rhino/GH runtime inside Revit process | RiR is a geometry pipe; we add the semantic layer that turns GH output into *native* Revit elements, and RiR is an execution backend option (Phase 12) |
| **Ordinary Revit add-ins** | Fixed-function buttons | We are a *platform*: module registry, AI surface, cross-app orchestration |
| **Ordinary MCP servers** | Tool lists bolted to one API | We add the things production BIM needs: mutation metadata, approval queue, transaction discipline, identity mapping across apps, semantic graph, audit trail |

**Moat in one sentence:** the only tool where an AI agent can safely *read, reason about, and — with human approval — modify* a live Revit model using native elements, and carry those semantics across Rhino, Navisworks, IFC, Speckle, and Power BI.

## 5. The plugin-style app vision

Not a script collection. The user experience:

- **Ribbon tab "AEC Bridge"** (exists today with Connection/Tools panels) grows to ~5 product commands: *Open Panel, Run Health Check, Review Pending Actions, Reports, Settings*.
- **Dockable panel** (WPF + WebView2): chat with the model, see proposed actions as structured cards (element counts, parameter diffs), **Approve / Reject / Approve-all-similar**, live run log.
- **Modules** (see `PLUGIN_MODULE_SYSTEM.md`): Model Inspector, QA/QC Checker, Parameter Manager, Report Generator… discovered from a registry, each declaring its commands, permissions, and schemas.
- **Everything auditable**: every mutation is a logged, transaction-named, reversible action tied to the approving user.

## 6. Role of each layer

- **AI agents** — intent → plan → tool calls. Agents *propose*; they never mutate silently. Long tasks run through the existing `JobManager` (`job_status`/`job_cancel`).
- **MCP tools** — the stable contract. Today: 100 `revit_*`, 19 `rhino_*`, 7 `ifc_*`, 7 `graph_*`, 17 `speckle_*`, 12 `autodesk_*`, 3 `aec_*` mapper, 3 exporter, 2 job tools. Gap to close: `is_mutating`/`execution_mode` metadata on the Python side (C# already has it via `[BridgeCommand]`).
- **Revit-native automation** — all mutations happen as native elements inside named `Transaction`s on the API thread via the existing `ExternalEvent`/`CommandQueue` path. **DirectShape only for preview or explicit fallback** — never the deliverable.

## 7. Top daily-dependence workflows

Ranked by (frequency × pain × feasibility) — full specs in `AEC_WORKFLOW_CATALOG.md`:

1. **Ask the model** — natural-language Q&A over elements/params/levels/views (read-only; builds trust).
2. **Model health check** — one click → rule-based QA report with clickable element IDs.
3. **Bulk parameter ops with approval** — preview diff → approve → transactional apply → rollback available.
4. **Sheet/view automation** — batch sheets from CSV, renumber, apply templates (tools already exist: `revit_batch_create_sheets_from_csv`, `revit_renumber_sheets`, `revit_apply_view_template`).
5. **BIM report export** — model → SQLite/Excel/Power BI (exporter + PowerBI switch).
6. **Façade roundtrip** (flagship, post-MVP) — GH diagrid → semantic panels → native curtain panels.

## 8. MVP direction

Ship the **three data workflows** (inspect → validate → fix) on **one semantic layer** with the **approval panel**, targeting Revit 2024 (net48) + 2025/26 (net8) — multi-targeting already exists in `RevitBridge.csproj`. Detail in `MVP_EXECUTION_PLAN.md`.

Explicitly **not** MVP: façade configurator, Navisworks/PowerBI registration fixes beyond health, orchestrator/recipes, cloud/remote MCP, marketplace.

## 9. Long-term direction

- **Phase-2 flagship:** façade configurator roundtrip (Rhino/GH → semantic panel schema → native Revit), proving the semantic layer publicly.
- **Orchestrator** (roadmap Phase C): YAML recipes spanning switches — "export Revit → clash in Navisworks → dashboard in Power BI".
- **Data plane** (roadmap Phase D): Parquet/DuckDB, `.pbit` templates, IDS validation.
- **Open-core:** GPL platform + commercial modules/enterprise features (dual license already in `LICENSING.md`; strategy details stay in the private strategy doc, not here).
- **Ecosystem:** module marketplace, switch SDK for third-party hosts (Archicad, Tekla — roadmap Phase G).
