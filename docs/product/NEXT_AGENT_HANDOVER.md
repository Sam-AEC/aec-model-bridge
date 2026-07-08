# Next Agent Handover

**Session:** 2026-07-08, planning/scaffolding only — **no production code written, nothing deleted.**

## What was inspected
Full repo audit (delegated to an Explore subagent): all root + `docs/` markdown, all 5 packages (hub providers/servers/tests, Revit add-in incl. `BridgeCommandFactory.cs` and csproj exclusions, Rhino/Navisworks bridges, PowerBI tool), `scripts/`, `dist/`, `server.json`, git log vs CHANGELOG. Findings preserved in `CURRENT_REPO_AUDIT.md`.

## What was created (all new, in `docs/product/`)
`AEC_MODEL_BRIDGE_PRODUCT_VISION.md` · `CURRENT_REPO_AUDIT.md` · `PLUGIN_APP_ARCHITECTURE.md` · `AEC_WORKFLOW_CATALOG.md` (W1–W16) · `INTEGRATION_STRATEGY.md` (18 integrations, P0–Future) · `PLUGIN_MODULE_SYSTEM.md` · `SEMANTIC_BIM_DATA_MODEL.md` · `AI_AGENT_SWARM_PLAN.md` (14 agents) · `SCAFFOLDING_TASK_LIST.md` (Phases 0–21) · `MVP_EXECUTION_PLAN.md` · `DECISIONS_AND_RISKS.md` · this file.

## What was NOT changed
No existing file edited or deleted. CLAUDE.md still has the wrong Navisworks port (3005→3002) and dead backlog pointer; README links still broken; `docs/security.md` still stale; 260 MB stray `.3dm*` binaries still in `docs/`; private strategy doc still in repo; versions still 1.1.0 vs CHANGELOG 1.2.0. All of that is **Phase 0** work awaiting Sam's approval of the deletion list (`CURRENT_REPO_AUDIT.md` §9).

## Main findings (from the audit)
1. Shipped hub = `mcp_server.py`, 9 providers, ~170 tools; a **legacy parallel server** (`server.py` + 25-tool `tools/` system) confuses tests and docs, and has a real bug (`proxy._connect()` doesn't exist).
2. **Navisworks provider is not registered** in the shipped hub; **PowerBI provider registered nowhere** — both are advertised as working.
3. Revit add-in is solid (110 attribute-registered commands, correct ExternalEvent threading), but `src/Commands/**` is a compile-excluded dead tree, and **Contract v2 auth exists but LegacyMode (port 3000, no auth) is the runtime default**.
4. The approval/destructive-action layer documented in `docs/security.md` **was never implemented** — it is the MVP's core build item.
5. Four competing product names; D-001 fixes it as **AEC Model Bridge**.

## Decisions locked with Sam (see DECISIONS_AND_RISKS.md)
D-001 name · D-002 MVP = inspect/QA-QC/parameters, façade deferred to flagship · D-003 normal-Revit-user audience with dockable panel + approvals · D-005 net48+net8 targets · D-014 docs in `docs/product/`, strategy-free.

## Biggest risks
R12 (silent AI mutation — the gate must be default-on and agent-unapprovable), R2 (snapshot perf on large models), R8 (WebView2-in-Revit spike unproven), D-013 (92 MB binaries may warrant history rewrite — needs Sam).

## Recommended next task
**Phase 0** (`SCAFFOLDING_TASK_LIST.md`): present the §9 deletion list to Sam, then execute the doc/version cleanup. It's low-risk, unblocks everything, and makes the repo stop contradicting itself. First *code* task after that: **P4.1 tool metadata + P4.2 approval gate** (pure Python, testable without Revit open).

## Exact next prompt
> Read docs/product/NEXT_AGENT_HANDOVER.md and docs/product/SCAFFOLDING_TASK_LIST.md. Execute Phase 0: first show me the deletion/untrack/move list from CURRENT_REPO_AUDIT.md §9 for approval, then apply approved items, fix CLAUDE.md (port 3002, backlog pointer → docs/product/SCAFFOLDING_TASK_LIST.md, retitle AEC Model Bridge), fix README broken links and the Rhino transport description, rewrite docs/security.md against the as-built provider system, and reconcile versions to CHANGELOG. Commit in logical chunks on development, no Co-Authored-By trailers.
