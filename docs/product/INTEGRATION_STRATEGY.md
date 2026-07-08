# Integration Strategy

Priorities: **P0** = MVP, **P1** = flagship/next, **P2** = after P1, **Future**. "Exists" reflects the audit in `CURRENT_REPO_AUDIT.md`.

| # | Integration | Priority | Exists today |
|---|---|---|---|
| 1 | Revit API | P0 | 110 C# commands / 100 MCP tools ✓ |
| 2 | MCP | P0 | hub + 9 providers ✓ |
| 3 | Claude Code | P0 | via MCP stdio ✓ |
| 4 | VS Code | P0 | via MCP config ✓ |
| 5 | GitHub | P0 | repo/CI workflows ✓ |
| 6 | Excel | P0 | ✗ (SQLite exists; xlsx new) |
| 7 | IFC | P0 | 7 tools ✓ |
| 8 | Rhino / Grasshopper | P1 | 19 tools + bridge :3004 ✓ |
| 9 | Rhino.Inside.Revit | P1 | ✗ |
| 10 | Speckle | P1 | 17 tools ✓ (OAuth) |
| 11 | Navisworks | P1 | C# 16 cmds ✓ / provider unregistered ✗ |
| 12 | Power BI | P1 | C# tool :3006 partial / provider orphaned ✗ |
| 13 | Dynamo | P2 | scratch prototypes only |
| 14 | DuckDB / Parquet | P2 | ✗ (roadmap Phase D) |
| 15 | APS / ACC | P2 | 12 tools ✓ (OAuth) |
| 16 | Local AI agents (BYO-LLM) | P2 | ✗ (roadmap Phase H) |
| 17 | MS Graph | Future | ✗ |
| 18 | Cloud / remote MCP | Future | ✗ (roadmap Phase H) |

---

### 1. Revit API — P0
- **Purpose/value:** the product's substrate; native reads/writes. **Data:** elements, params, views, sheets, transactions.
- **Method:** existing add-in (`HttpListener` → `ExternalEvent` → `BridgeCommandFactory`), Contract v2 flipped to default. Multi-target net48 (2024) + net8 (2025/26); net10 (2027) stays experimental.
- **SDK:** RevitAPI.dll local or `Nice3point.Revit.Api.*` (both wired).
- **MVP:** stabilize 110 commands, add snapshot extraction command, mutation metadata parity. **Advanced:** revive/kill dead `Commands/**` tree per subsystem; worksharing-aware writes.
- **Risks:** API-thread deadlocks (mitigated by existing queue); version drift across targets. **Test:** e2e against canonical model per Revit version (CI matrix where licensable; else scripted local runs). 

### 2. MCP — P0
- **Purpose:** stable machine contract for all agents/clients. **Data:** tool schemas, results, job refs.
- **Method:** `mcp_server.py` only (retire `server.py`); `ProviderTool` gains `is_mutating`/`destructive`/`execution_mode`/`permissions`; regenerate `tools-generated.md`.
- **MVP:** metadata + approval-gate tools (`plan_actions`, `approve_plan`, `list_pending_plans`). **Advanced:** MCP resources for snapshots, prompts for common workflows.
- **Risks:** spec evolution (`mcp>=0.9.0` pin — track SDK releases); tool-count bloat degrading agent tool choice (group via module namespacing). **Test:** existing `test_provider_contract.py` extended to assert metadata on every tool.

### 3. Claude Code — P0
- **Purpose:** expert surface + the swarm that builds the product. **Method:** `server.json` MCP config; project skills (`/rhino-god-mode` exists); `CLAUDE.md` corrections (ports, backlog pointer).
- **MVP:** clean install docs + working config. **Advanced:** packaged workflow skills (`/model-health`, `/param-batch`). **Risk:** none structural. **Test:** fresh-clone smoke script.

### 4. VS Code — P0
- **Purpose:** developer/automation-engineer surface. **Method:** same MCP server via VS Code MCP config; no bespoke extension for MVP (Future: status/log viewer extension). **Test:** documented setup walkthrough.

### 5. GitHub — P0
- **Purpose:** CI, releases, module distribution. **Method:** existing repo + Actions: pytest + `dotnet build` matrix (net48/net8), DLL license scan (exists per LICENSING), release artifacts (installer + wheel). **MVP:** CI green on both stacks. **Advanced:** module marketplace via releases/registry repo. **Risk:** Revit API DLLs not redistributable — CI uses Nice3point NuGet fallback (already supported).

### 6. Excel — P0
- **Purpose:** the report format management actually opens. **Data:** element/param/finding tables; CSV param roundtrip.
- **Method:** `openpyxl` in hub (`export_excel` tool). **MVP:** 3-sheet workbook (elements, parameters, findings). **Advanced:** formatted QA dashboards, roundtrip validation. **Risks:** file locks; huge sheets (row cap + link to SQLite). **Test:** golden workbook diff on canonical model.

### 7. IFC — P0
- **Purpose:** open-standard read/validation lane; non-Revit data QA. **Data:** GlobalId, spatial tree, psets.
- **Method:** `ifcopenshell` provider (exists, 7 tools) + mapper (GlobalId↔UniqueId). **MVP:** IFC Q&A + Revit-vs-IFC comparison. **Advanced:** IDS validation (Phase D), IFC export QA (`revit_export_ifc` then re-validate). **Risks:** ifcopenshell wheel/platform pinning. **Test:** sample IFC fixtures in repo.

### 8. Rhino / Grasshopper — P1
- **Purpose:** computational design lane; façade flagship. **Data:** panel geometry, semantic zone specs, preview meshes.
- **Method:** existing C# bridge :3004 (`run_python` is the workhorse) + MCP `g1_*` GH canvas tools; GH emits semantic spec JSON, not meshes.
- **MVP(P1):** façade zone spec exporter GH definition. **Advanced:** live-link, `CurtainWallDetailer`/`DiagridGenerator` productization. **Risks:** RhinoCommon v7 vs v8 API drift (reflection helpers exist); hardcoded port (move to Contract v2). **Test:** scripted Rhino headless run → spec → golden diff.

### 9. Rhino.Inside.Revit — P1
- **Purpose:** GH against live Revit geometry, in-process. **Method:** custom GH components wrapping hub endpoints; RiR emits semantic specs → ActionPlans (no write bypass).
- **SDK:** RiR nuget/SDK; supported version matrix documented. **MVP(P1):** one exemplar definition. **Advanced:** Revit-selection-driven GH inputs. **Risks:** RiR/Rhino/Revit version triangle; load order with our add-in. **Test:** manual matrix checklist + exemplar run.

### 10. Speckle — P1
- **Purpose:** versioned transport + web viewing + external collaborators. **Data:** semantic snapshots as Speckle objects.
- **Method:** 17 existing tools (`specklepy>=3`); publish snapshot → receive delta → W14 reconciliation. **MVP(P1):** publish/receive snapshot roundtrip. **Advanced:** branch-per-variant façade workflow. **Risks:** Speckle v3 API churn; OAuth token lifetime (refresh exists). **Test:** `test_cloud_providers.py` extended with mock server (exists) + live smoke.

### 11. Navisworks — P1
- **Purpose:** coordination/clash results back into the loop. **Data:** model tree, clash tests/results, viewpoints.
- **Method:** **register `NavisworksProvider` in `mcp_server.py`** and widen it to the 16 C# commands (`navis.run_clash_test`, `navis.get_clash_results`, viewpoints, tree); clash GUIDs → mapper → Revit selection.
- **MVP(P1):** health + model tree + clash results → Revit element selection. **Advanced:** auto-viewpoint per QA finding; NWD export pipeline from `revit_export_navisworks` (exists). **Risks:** Navisworks COM quirks; GUID mapping fidelity. **Test:** RVT+NWF fixture pair.

### 12. Power BI — P1
- **Purpose:** live dashboards; "ask your dashboard" DAX Q&A. **Data:** DAX queries/results; exported tables.
- **Method (two lanes):** (a) file lane — SQLite→(later Parquet) + shipped `.pbit`; (b) live lane — wire orphaned `PowerBIProvider` to the :3006 ADOMD external tool.
- **MVP(P1):** file lane + provider registration with health. **Advanced:** DAX Q&A, auto-refresh. **Risks:** external-tool launch args change per PBI session (re-handshake needed); ADOMD licensing/runtime deps. **Test:** DAX smoke against a fixture PBIX.

### 13. Dynamo — P2
- **Purpose:** meet Revit users where they are. **Method:** ZeroTouch node package calling hub HTTP; nodes = thin wrappers over the same semantic spec + gate. **MVP(P2):** 5 nodes (connect, snapshot, query, plan, apply). **Risks:** Dynamo versioning per Revit release. **Test:** sample graph in repo.

### 14. DuckDB / Parquet — P2 (roadmap Phase D)
- **Purpose:** analytics-grade data plane; multi-model portfolio queries. **Method:** exporter grows Parquet writer; DuckDB for local SQL; PBI reads Parquet. **MVP(P2):** Parquet mirror of SQLite schema. **Risks:** schema evolution discipline (`schema_version` from day one — see W8). **Test:** row-count parity SQLite↔Parquet.

### 15. APS / ACC — P2
- **Purpose:** cloud model/issue integration for enterprise. **Method:** 12 existing `autodesk_*` tools; QA findings → ACC Issues (`autodesk_data_create_issue` exists). **MVP(P2):** findings→Issues. **Risks:** APS app provisioning/scopes; rate limits. **Test:** mocked + sandbox hub.

### 16. Local AI agents / BYO-LLM — P2 (roadmap Phase H)
- **Purpose:** firms that can't send model data to cloud LLMs. **Method:** hub is client-agnostic already (MCP); document Ollama/LM Studio MCP-client setups; approval gate matters *more* here. **Risk:** small-model tool-choice quality → provide curated tool subsets per module.

### 17. MS Graph — Future
- Teams notifications of QA runs, SharePoint report drops, Planner tasks from findings. Method: Graph SDK in hub; requires tenant app registration. Park until enterprise pull.

### 18. Cloud / remote MCP — Future
- REST/OpenAPI facade + hosted hub (roadmap Phase H). Blockers: auth story beyond localhost bearer, multi-tenant workspace isolation. Do not start before packaging (Phase 19) is done.
