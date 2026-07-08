# AI Agent Swarm Plan

How Claude Code agents build this product in parallel without stepping on each other. Ground rules first, then the roster.

## Ground rules (all agents)

- **Source of truth:** `docs/product/*` (this package) for *what to build*; `docs/system-blueprint-and-workflows.md` + ADRs for *how the system works*; `SCAFFOLDING_TASK_LIST.md` for *task ownership*.
- **Conflict avoidance = ownership by path.** Each agent has "allowed edit areas"; editing outside them requires the orchestrating session's sign-off. Two agents never own the same path in the same phase.
- **Worktrees** (`EnterWorktree` / `isolation: worktree`): mandatory for any agent touching code in parallel with another code agent; unnecessary for single-agent doc work. C# and Python agents can share a branch only if their paths are disjoint (`packages/revit-bridge-addin` vs `packages/mcp-server-revit`).
- **Handover format (uniform):** every agent ends with: *changed files · commands run + results (build/test output verbatim) · contracts touched (tool names, schemas) · open questions · next task recommendation*. Written to the task's phase section or `NEXT_AGENT_HANDOVER.md`.
- **Required checks before "done":** Python — `pytest` + `ruff`; C# — `dotnet build -c Release` for **net48 and net8** targets; docs — no broken relative links; contract changes — regenerate `docs/tools-generated.md`.
- **Human approval required for:** deleting/archiving any existing file (audit §9 list), changing a shipped tool's name/schema (breaking change), flipping runtime defaults (LegacyMode, approval_mode), anything touching `LICENSES/`, `LICENSING.md`, `TRADEMARKS.md`, publishing/pushing, and any git history rewrite.
- **Model/effort:** exploration and doc-summarization agents run cheap (Explore/haiku-class); architecture and Revit-API-threading work runs at highest reasoning. Don't spawn an agent for work smaller than its briefing.

## Roster

| Agent | Responsibility | Inputs | Outputs | Allowed edit areas |
|---|---|---|---|---|
| **Repo Audit** | Keep `CURRENT_REPO_AUDIT.md` true; verify claims vs code after each phase; regen tool docs | whole repo (read) | audit doc updates, drift reports | `docs/product/CURRENT_REPO_AUDIT.md`, `docs/tools-generated.md` |
| **Product Architect** | Guard vision/architecture coherence; arbitrate cross-agent contract disputes; own ADRs | product package, ADRs | ADR updates, decision entries | `docs/product/*`, `docs/000*.md`, `DECISIONS_AND_RISKS.md` |
| **Revit API** | C# add-in: snapshot extraction command, transaction discipline, Contract v2 default, dockable pane host, dead-tree resolution | `PLUGIN_APP_ARCHITECTURE.md`, `SEMANTIC_BIM_DATA_MODEL.md`, `BridgeCommandFactory.cs` | C# code + `docs/revit-addin-lifecycle.md` updates | `packages/revit-bridge-addin/**` |
| **MCP Tooling** | Hub: tool metadata, approval-gate tools, module provider adapter, retire legacy `server.py`/`tools/`, register Navisworks | hub source, module spec | Python code + tests | `packages/mcp-server-revit/src/**`, `tests/**` |
| **Plugin App** | Module registry, built-in MVP modules (inspector, params, qaqc, reports, sheets, selection) | `PLUGIN_MODULE_SYSTEM.md`, workflow catalog | `modules/**` + manifests + tests | `packages/mcp-server-revit/src/revit_mcp_server/modules/**` |
| **Semantic BIM Data** | Snapshot/delta/zone schemas, diff engine, reconciliation, mapper extensions | `SEMANTIC_BIM_DATA_MODEL.md` | JSON schemas, `semantic/` package, tests | `packages/mcp-server-revit/src/revit_mcp_server/semantic/**`, `schemas/**` |
| **UI/UX** | WebView2 panel app (chat, plan cards, findings, run log), ribbon layout | architecture §2, workflow UI specs | panel HTML/JS/CSS + C# pane host (coordinate w/ Revit API agent) | `packages/revit-bridge-addin/src/UI/**`, `panel/**` |
| **Integration** | Speckle/APS/IFC/PowerBI wiring per `INTEGRATION_STRATEGY.md`; Excel exporter | strategy doc, provider code | provider updates, `export_excel` | `providers/cloud.py`, `providers/ifc.py`, `providers/powerbi.py`, `providers/exporter.py` |
| **Rhino/Grasshopper** | Façade zone spec exporter, bridge Contract v2, RiR exemplar, GH `g1_*` playbooks | `rhino-bridge-addin`, W11–W13, `/rhino-skills` | C# bridge updates, GH defs, scratch→product promotion | `packages/rhino-bridge-addin/**`, `modules/facade_configurator/**` |
| **QA/QC BIM** | Rule engine + core rule pack, issue store, golden findings; the domain expert for what rules matter | W7/W9, rule format | `rules/core/**`, rule engine in qaqc module | `modules/qaqc_checker/**` |
| **Testing** | Canonical test model script, e2e harness (extends `test_e2e.py`), CI matrix, contract tests for module metadata | all contracts | `tests/**`, `.github/workflows/**`, fixtures | `tests/**`, `.github/**`, `fixtures/**` |
| **Documentation** | User docs, tutorials, rewrite stale `docs/security.md`, fix README links/CLAUDE.md ports, MkDocs site | audit §4 stale list | docs | `docs/**` (not `docs/product/` — Architect owns), `README.md`, `CLAUDE.md` |
| **Release** | Version reconciliation (1.1.0→CHANGELOG parity), installers, `server.json`, marketplace listings | `docs/build-and-install-scripts.md`, `marketplaces.md` | scripts, installer defs, release notes | `scripts/**`, `dist/` config (not artifacts), `server.json`, `CHANGELOG.md` |
| **Security/Safety** | Approval gate review, permission enforcement tests, redaction coverage, bearer-token default flip, threat model refresh | ADR 0002, gate code | security tests, `docs/security.md` (with Documentation agent), threat notes | `tests/test_security*.py`, review-only elsewhere |

## Parallelization map

- **Wave 1 (independent):** Revit API (snapshot command, C#) ∥ MCP Tooling (metadata + gate, Python) ∥ Documentation (stale-doc cleanup) ∥ Testing (test model script). Different path ownership → same branch or worktrees, no conflicts.
- **Wave 2 (after gate + snapshot):** Plugin App (modules) ∥ UI/UX (panel) ∥ Semantic BIM Data (diff/reconcile) — modules mock the panel; panel mocks modules via the command-list endpoint contract fixed in Wave 1.
- **Wave 3:** QA/QC rules ∥ Integration wiring ∥ Release packaging.
- **Contract freeze points:** tool metadata shape (end W1), `module.json` schema (start W2), snapshot schema (start W2). After a freeze, changes go through Product Architect + human approval.
- **Merge order:** hub contracts → C# → modules → UI. The orchestrating session (main Claude Code context) merges; agents never merge to `development` themselves.

## When human (Sam) must decide

1. Audit §9 deletions/archival (260 MB binaries, private strategy doc, dead C# tree, legacy server).
2. LegacyMode/auth default flip (breaks existing local setups).
3. Any tool rename on the shipped ~170-tool surface.
4. Installer signing, marketplace publishing, license/pricing surfaces.
5. Approving each phase's Definition of Done in `SCAFFOLDING_TASK_LIST.md`.
