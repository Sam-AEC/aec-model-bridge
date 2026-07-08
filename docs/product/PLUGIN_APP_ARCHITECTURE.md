# Plugin App Architecture

Builds on what exists: `revit-bridge-addin` (110 commands, ExternalEvent path), the Python hub (9 providers, ~170 tools), ADR 0001/0002. New layers are marked **[NEW]**.

## 1. Layer map

```
┌─ Surface ──────────────────────────────────────────────────────────┐
│ Revit dockable panel [NEW]   Ribbon tab (exists, grows)            │
│ Claude Code / MCP clients (exists)   VS Code (exists via MCP)      │
├─ AI agent layer ───────────────────────────────────────────────────┤
│ Claude via MCP stdio (exists) · agent proposes ActionPlans [NEW]   │
├─ Hub (Python, packages/mcp-server-revit) ──────────────────────────┤
│ mcp_server.py · ProviderRegistry (exists)                          │
│ Approval Gate [NEW] · Module Registry [NEW] · Audit log (extend)   │
│ Semantic BIM layer [NEW] · IdentityMapper/Graph/Exporter (exist)   │
│ JobManager async (exists) · Redaction/workspace sandbox (exist)    │
├─ Switches (C# HTTP, Contract v2) ──────────────────────────────────┤
│ Revit :3000/v2 (exists) · Rhino :3004 · Navis :3002 · PBI :3006    │
├─ Host APIs ────────────────────────────────────────────────────────┤
│ Revit API (ExternalEvent+Transaction) · RhinoCommon · Navis .NET   │
└────────────────────────────────────────────────────────────────────┘
```

## 2. Revit add-in layer (C#)

Keep the proven pipeline: `BridgeServer` (HttpListener) → `CommandQueue.Enqueue` → `ExternalEvent.Raise()` → `RevitCommandExecutor` on API thread → `BridgeCommandFactory`.

Changes:
- **Contract v2 becomes default** (flip `LegacyMode`): dynamic loopback port, registry file `%LOCALAPPDATA%\AECModelBridge\registry\revit-<pid>.json`, bearer token on `/execute`. Kill unauthenticated :3000 default. (D-006)
- **Transaction discipline [NEW policy]:** every mutating handler wraps exactly one named `Transaction` (`"AMB: <module>.<command> #<action_id>"`). Multi-step actions use `TransactionGroup` and assimilate. Name = the undo entry the user sees; `action_id` links Revit undo history to the audit log.
- **Dockable panel [NEW]:** `IDockablePaneProvider` hosting **WebView2**; panel UI is HTML/JS talking to the add-in over the WebView2 message bridge, and to the hub via localhost. WPF only for the pane chrome. Rationale: web UI iterates fast, reuses across hosts later.
- **Ribbon:** existing `AEC Bridge` tab grows to: Open Panel · Run Health Check · Review Pending Actions · Reports · Settings.
- **Dead tree decision:** `src/Commands/**` (compile-excluded) is deleted or revived per subsystem — audit item, human call (D-011).

## 3. MCP server layer (Python hub)

- **One server.** `mcp_server.py` is canonical; `server.py` + legacy `tools/` retire after test migration (D-004).
- **Register the strays:** NavisworksProvider into `mcp_server.py`; PowerBIProvider wired or explicitly parked.
- **Tool metadata [NEW]:** extend `ProviderTool` with `is_mutating: bool`, `destructive: bool`, `execution_mode: sync|async`, `permissions: [str]` — mirrored from the C# `[BridgeCommand]` attributes so `tools-generated.md` stops printing "?".

## 4. Safety & approval layer [NEW — the core product build]

The keystone. `docs/security.md` documents `allow_destructive`/`destructive_confirm` keys that were never implemented; this replaces them.

- **ActionPlan:** agents that want to mutate call `plan_actions` (new hub tool) with a list of intended tool calls + args. Hub validates schemas, dry-runs read-side (element counts, parameter before-values), returns a plan with `plan_id` and per-action diffs.
- **Approval Gate:** mutating tools called without an approved `plan_id` are rejected when `approval_mode=required` (default in panel mode; `auto` available for headless/expert use, off by default). Pending plans surface in the dockable panel as cards → Approve / Reject / Approve-all-similar.
- **Execution:** approved plan executes through the normal provider path; each action's transaction carries the `action_id`.
- **Rollback:** per-action = Revit undo (named transaction); per-plan = `TransactionGroup` rollback while open, otherwise a generated inverse plan (e.g. restore captured before-values for parameter writes) — inverse plans only for reversible action types; others marked `irreversible: true` and require explicit confirm.
- Enforcement lives in the **hub** (single choke point for all switches); the C# `ConfirmationRequired` attribute stays as defense-in-depth for direct HTTP callers.

## 5. Logging & audit

Extend the existing two-layer logging (`docs/logging-and-audit.md`): add an **audit ledger** (JSONL, `%LOCALAPPDATA%\AECModelBridge\audit\<doc-guid>\*.jsonl`): `{ts, user, agent, plan_id, action_id, tool, args_redacted, element_uids, before, after, result, transaction_name}`. Panel run-log reads this. Redaction pipeline (exists) applies before write.

## 6. Data extraction & semantic BIM layer

- **Extraction (exists):** `revit_list_elements`, `revit_get_element_parameters`, exporter → SQLite; IFC provider; graph provider.
- **Semantic layer [NEW]:** typed element snapshots keyed by **Revit UniqueId**, with category/type/host/level/room relations — schema in `SEMANTIC_BIM_DATA_MODEL.md`. Built on `IdentityMapper` (exists) for cross-app identity. This is what QA rules, diffs, reports, and the façade roundtrip all consume — build once.

## 7. Module registry & tool execution [NEW]

Modules = manifest (JSON) + Python module class exposing commands that compose existing MCP tools; C# only when a new host-side primitive is needed. Discovery: `modules/` dir + entry points. Full spec: `PLUGIN_MODULE_SYSTEM.md`. Execution routes through the same registry → approval gate → provider path; long tasks via `JobManager`.

## 8. Integration & reporting layers

- Integration: providers (exist) + identity mapper + Contract v2 registry discovery. Strategy per system: `INTEGRATION_STRATEGY.md`.
- Reporting: semantic snapshot → SQLite (exists) → Excel (openpyxl [NEW]) → Power BI (switch DAX or file-based). DuckDB/Parquet later (roadmap Phase D).

## 9. Packaging & installer

- Per-host add-in MSI/EXE (WiX or Inno) installing `.addin` + multi-target DLLs into version folders (build scripts exist: `docs/build-and-install-scripts.md`).
- Hub via `pipx install aec-model-bridge` or bundled runtime in the installer (decide at Phase 19; bundled favors non-programmers).
- MCP client config via existing `server.json` / marketplace listing (`docs/marketplaces.md`).

## 10. What belongs where

| Concern | Home |
|---|---|
| Anything touching Revit API objects, transactions, ExternalEvent, dockable pane hosting | **C# add-in** |
| Providers, approval gate, module registry, semantic layer, identity, jobs, exporters, QA rules, report generation | **Python hub** |
| Stable, schema'd, metadata-rich contract for agents; one tool = one capability | **MCP tools** |
| Chat, plan cards, approve/reject, run log, report viewer (WebView2 HTML/JS) | **Plugin UI** |
| Multi-step reasoning, repo/dev automation, orchestration recipes | **Claude Code / agent layer** |
| OAuth'd cloud data (Speckle/APS), file formats (IFC), BI (DAX) | **External integrations via providers** |
| Preview meshes only — GH previews, Navis overlay. **Never** deliverable geometry; native elements or explicit fallback with user consent | **DirectShape / dumb geometry** |
