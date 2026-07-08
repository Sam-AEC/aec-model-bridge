# Current Repo Audit — aec-model-bridge

Audited 2026-07-08 on branch `development`. **Nothing was deleted or moved.** Files flagged for consolidation/archival are listed in §9 pending approval.

## 1. Identity

Four names in circulation — the single biggest branding problem:

| Name | Where | Verdict |
|---|---|---|
| **AEC Model Bridge** | README, LICENSING, `pyproject.toml` (`aec-model-bridge`), `server.json`, `Server("aec-model-bridge")`, logo | **Canonical** (decision D-001) |
| AEC Omni-Bridge | CLAUDE.md title, ecosystem-strategy doc, blueprint | Legacy narrative brand — migrate |
| Autodesk-Revit-MCP-Server | Local folder name only | Stale; remote is already `Sam-AEC/aec-model-bridge` |
| RevitBridge / AECModelBridge | C#: namespace `RevitBridge`, assembly `AECModelBridge`, both `dist/RevitMCP/` and `dist/AECModelBridge/` exist | Mid-flight rename; reconcile |

Also: `server.json`/`pyproject.toml` descriptions still say "for Autodesk Revit" despite multi-platform positioning; package `mcp-server-revit` / module `revit_mcp_server` are Revit-centric names for a multi-provider hub.

## 2. Packages

### `packages/mcp-server-revit` (Python hub) — mature, with dead weight
- Python ≥3.11; deps: `mcp`, `pydantic`, `httpx`, `ifcopenshell`, `networkx`, `specklepy>=3,<4`.
- **Shipped server:** `src/revit_mcp_server/mcp_server.py` — MCP stdio, registers **9 providers**: Revit, IFC, AECMapper, SQLiteExporter, Job, Rhino, SemanticGraph, Speckle, AutodeskData. Proxy via `MCP_PROXY_TARGETS`.
- **Legacy server (dead-parallel):** `server.py` — line-JSON protocol, registers Navisworks (shipped server doesn't), uses different env var `MCP_PROXY_URL`, and calls `proxy._connect()` **which does not exist** on `McpProxyProvider`. Several tests target this server, not the shipped one.
- **Orphaned legacy tool system:** `tools/handlers.py`, `tools/document.py`, `tools/health.py`, `schemas.py` — the pre-provider 25-tool system that `docs/security.md` still documents.
- Providers dir: `base.py`, `registry.py`, `revit.py`, `ifc.py`, `identity_mapper.py`, `rhino.py`, `navisworks.py`, `graph.py`, `cloud.py`, `job_provider.py`, `exporter.py`, `proxy.py`, `powerbi.py` (orphaned), `fake.py` (test-only).
- Tests: 14 modules incl. provider-contract and perf; good breadth but partly aimed at legacy code.

### `packages/revit-bridge-addin` (C#) — flagship, operational
- Multi-target **net48 / net8.0-windows / net10.0-windows** (Revit 2024/2025-26/2027). Serilog, IronPython, Revit API via local DLLs or Nice3point NuGet fallback.
- `App.cs` (IExternalApplication) → `CommandQueue` → `ExternalEvent` → `RevitCommandExecutor` → `BridgeCommandFactory`. Correct API-thread discipline.
- `BridgeServer.cs`: `/health`, `/tools`, `/capabilities`, `POST /execute`; semaphore(10); 5 MB cap. **Contract v2 (dynamic port + bearer token + registry file) implemented but OFF by default** — `LegacyMode` defaults true → fixed port 3000, no auth, unless `MCP_REVIT_LEGACY_PORT=false`.
- **Real surface: 110 `[BridgeCommand("revit.*")]` handlers** in `BridgeCommandFactory.cs` (~4,300 lines), attribute carries `IsMutating`/`ConfirmationRequired`.
- **Dead tree:** `src/Commands/Core|Advanced|Specialized|Enhancements/**` (Family/Geometry/MEP/Stairs/Structural/Worksharing commands, `Phase*CommandRegistry`) — `<Compile Remove>`d in `RevitBridge.csproj:67-73`, zero `[BridgeCommand]` attributes, never in the shipped DLL.

### `packages/rhino-bridge-addin` (C#) — built ✓
- net48, RhinoCommon 7.16, hardcoded port **3004**, `switch`-based routing (not the attribute pattern).
- ~18 commands: doc/scene/layers, primitives, booleans, materials, transforms, `run_python` (IronPython), `generate_diagrid_tower`, reflection trio.

### `packages/navisworks-bridge-addin` (C#) — routing infra only
- net48, port **3002** (or Contract-v2 dynamic). **16 attribute-registered commands** incl. model tree, viewpoints, clash tests.
- **But:** Python `NavisworksProvider` exposes only 4 tools and is registered **only in legacy `server.py`** → the entire C# surface is unreachable through the shipped hub.

### `packages/powerbi-bridge-tool` (C#) — stub, fully orphaned
- External-tool console app (`AdomdClient`, port **3006**), `.pbitool.json` configs, root `deploy_pbi.ps1`.
- `providers/powerbi.py` (5 tools incl. `powerbi_execute_dax`) is **imported/registered nowhere**. No PowerBI tool is reachable.

## 3. MCP tool inventory (shipped hub, ~170 tools)

| Provider | Count | Tools |
|---|---|---|
| Revit | 100 | `revit_*`: doc/health (7), modeling (12), elements (21), views/sheets (15), parameters (11), annotation (5), materials/QA (4), exports (5), groups/worksharing (9), schedules/phasing (7), escape hatches `revit_invoke_method` / `revit_reflect_get` / `revit_reflect_set` / `revit_execute_python` |
| Rhino | 19 | `rhino_*` incl. `rhino_run_python`, `rhino_generate_diagrid_tower` |
| Speckle | 17 | OAuth-PKCE + projects/models/versions/publish/merge |
| Autodesk/APS | 12 | OAuth + hubs/projects/items/issues |
| IFC | 7 | metadata, spatial structure, query, properties, bbox, validate |
| Semantic graph | 7 | `graph_compile`, relations, clash/disconnected/load audits |
| Mapper | 3 | `aec_translate_id`, `aec_register_mapping`, `aec_map_workspace_path` |
| Exporter | 3 | SQLite model + graph export |
| Jobs | 2 | `job_status`, `job_cancel` |

**Defined but NOT reachable:** Navisworks (4 tools, legacy server only), PowerBI (5 tools, nowhere), `fake_tool` (tests), proxy tools (env-gated).

## 4. Docs inventory

| File | Verdict |
|---|---|
| `README.md` | Good landing, but **broken links** to nonexistent `docs/tools.md`, `docs/architecture.md`, `docs/integration-expansion-handover.md`; describes Rhino via SSE :9876 (as-built is HTTP :3004); presents Navisworks as shipped |
| `CHANGELOG.md` | At 1.2.0 while `pyproject.toml`/`RevitBridge.csproj`/`server.json` say **1.1.0** |
| `CLAUDE.md` | Titled "Omni-Bridge"; **wrong Navisworks port (3005 vs 3002)**; points to nonexistent `docs/agent-task-plan.md` as "canonical backlog" |
| `docs/0001-multi-provider-architecture.md` | Accurate ADR, status still "Proposed" though built — flip to Accepted |
| `docs/0002-switch-contract-v2.md` | Accurate; note v2 is opt-in at runtime |
| `docs/0007-hub-performance-posture.md` | Current |
| `docs/system-blueprint-and-workflows.md` | **Most valuable doc** (36 KB, self-auditing §0), but references deleted docs and gone `providers/speckle.py` |
| `docs/roadmap-and-plans.md` | Real roadmap (Phases A–I); overstates Navisworks/PowerBI as shipped; overlaps blueprint §10 |
| `docs/security.md` | **Most stale doc**: documents the dead 25-tool system and config keys (`allow_destructive`, `allowed_tools`, `destructive_confirm`) that **don't exist in `config.py`**; contradicts ADR 0002 on auth |
| `docs/tools-generated.md` | Auto-generated; lists Navisworks/PowerBI tools the hub doesn't register; `Mutating?` columns all "?" (metadata gap) |
| `docs/ecosystem-strategy-and-monetization.md` | Flagged private, **currently committed to a public-destined repo — exposure risk** |
| `configuration-reference.md`, `install.md`, `build-and-install-scripts.md`, `marketplaces.md`, `revit-addin-lifecycle.md`, `logging-and-audit.md` | Current and accurate |
| `target-frameworks-and-dependencies.md` | Mostly current; dependency list omits `mcp`, `ifcopenshell`, `networkx`, `specklepy` |
| CONTRIBUTING / LICENSING / SECURITY / TRADEMARKS / NOTICE | Current; licensing hygiene is genuinely mature |

## 5. As-documented vs as-built divergences

1. Navisworks switch advertised; provider unregistered in shipped hub.
2. PowerBI advertised (badges, CHANGELOG, commit 949d2e5); provider orphaned.
3. README says Rhino = SSE :9876/Rhino.Compute; reality = HTTP :3004 provider.
4. Two hub servers; tests split across them; `server.py` has the `_connect()` bug.
5. Source tree advertises MEP/stairs/structural command modules that are compile-excluded.
6. `security.md` says "no auth" while ADR 0002 + code implement bearer tokens — but LegacyMode default makes "no auth" the *runtime* truth. Both docs need one story.
7. Approval/destructive-action config documented but not implemented → this is the MVP's core build item, not a config fix.
8. Version drift 1.2.0 vs 1.1.0; port drift (CLAUDE.md Navis 3005 vs 3002).

## 6. Strong

- Provider abstraction (`AECProvider` + registry) — adding an integration is one class.
- 110 working Revit commands with correct ExternalEvent threading + IronPython escape hatch.
- Async jobs, PII/path redaction, workspace sandboxing, semantic graph, SQLite exporter, OAuth-PKCE cloud connectors.
- 14-module test suite incl. contract + perf tests; mock mode for CI.
- ADRs + self-auditing blueprint; mature dual-licensing/trademark hygiene; multi-target C# build already in place.

## 7. Weak

- Naming chaos (§1). Two servers + legacy tool system obscure the real surface.
- Doc drift everywhere a user would look first (README links, security.md, tool catalog).
- Advertised-but-unreachable connectors erode trust in all other claims.
- No mutation metadata on Python tools; no approval layer; no UI beyond ribbon stub.
- ~260 MB stray Rhino binaries in `docs/` (`Untitled*.3dm/.3dmbak/.rhl`); stray `Omni_LiveGeometryStats.csv`; tracked caches (`.pytest_cache/`, `.ruff_cache/`); committed `dist/` incl. legacy `dist/RevitMCP/`.

## 8. Missing

- Approval/undo layer (the product's core promise). Dockable panel UI. Module registry. Semantic BIM schema (identity mapper exists; no element-level roundtrip schema). Orchestrator/recipes (Phase C). Parquet/DuckDB + `.pbit` (Phase D). MkDocs site. `.env.example` covering `SPECKLE_CLIENT_ID`, `APS_CLIENT_ID`, `MCP_PROXY_TARGETS`, `MCP_REVIT_LEGACY_PORT`, etc.

## 9. Consolidation / archival candidates — **approval required before touching**

**Delete (accidental binaries):** `docs/Untitled.3dm`, `docs/Untitled2.3dm`, `docs/Untitled.3dmbak`, `docs/Untitled2.3dmbak`, `docs/Untitled.3dm.rhl` (~260 MB), `Omni_LiveGeometryStats.csv`.

**Untrack:** `dist/` (both trees; CONTRIBUTING says don't commit), `.pytest_cache/`, `.ruff_cache/`, empty `metrics/`.

**Move to private repo:** `docs/ecosystem-strategy-and-monetization.md`.

**Retire after test migration:** `revit_mcp_server/server.py`, `tools/{handlers,document,health}.py`, legacy parts of `schemas.py`, `providers/fake.py` (or move under `tests/`).

**Delete or revive (decide):** `packages/revit-bridge-addin/src/Commands/**` dead tree.

**Rewrite:** `docs/security.md` (against as-built), README links, CLAUDE.md port table + backlog pointer; regenerate `docs/tools-generated.md` after mutation-metadata work.

**Keep, reconcile:** `roadmap-and-plans.md` vs blueprint §10 overlap → roadmap stays strategy, blueprint stays architecture, this `docs/product/` package becomes the buildable plan; version bump artifacts to match CHANGELOG.
