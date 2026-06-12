# Chapter 2 — From Machine to Mainstream

**Status:** Roadmap chapter (v1.0, 2026-06-13)
**Companion docs:** `docs/agent-task-plan.md` v1.1 (the canonical backlog — all task cards live THERE, this doc never duplicates card text), `docs/system-blueprint-and-workflows.md` (architecture), root `PROMPT.md` + `AGENT.md` (Ralph loop files).
**Purpose:** Record the 2026-06-13 program review, the roadmap amendments it produced, the strategy for Chapter 2 (Phases H + I), and the dispatch kit for delegating the whole backlog to building agents.

---

## 1. Where the program stands (review verdict, 2026-06-13)

| Layer | State |
| --- | --- |
| Revit switch (C# add-in, 2024–2027) | **5/5** — operational, ~103 routes |
| Hub tool surface | **Real** — 157 MCP tools across 10 providers, 12 test suites, CI green incl. catalog drift check |
| IFC / graph / mapper / exporter / jobs | **4/5** — working headless core |
| Speckle / APS cloud providers | **3/5** — working, consolidation in flight (A1) |
| Navisworks switch | **1/5** — health-only stub |
| Orchestrator (recipes, Run Records, policy, discovery) | **0/5 — pure blueprint.** This is the entire value thesis and none of it is code yet |
| Phase A | 1 done (A0), 4 in flight (A1/A3/A5/A8), 4 open, 2 human |

**Verdict:** the switch layer is ahead of plan; the orchestration layer is the critical path; and the roadmap had a blind spot — it assumed MCP-native developer clients (Claude Desktop, VS Code) and had **no path for the average BIM professional using ChatGPT, Copilot, Gemini, or a local model, and no non-developer install story.** Chapter 2 closes that.

## 2. What the review changed (amendments to the v1.0 plan)

1. **Phase H added — Any-AI Access Layer (H1–H8).** Four doors into the hub: MCP stdio (today), remote MCP over Streamable HTTP (the universal door — Claude, ChatGPT connectors, Copilot Studio, Gemini all speak it as of 2026), a REST/OpenAPI facade (custom GPT Actions, n8n, Power Automate, Zapier), and a bundled bring-your-own-LLM chat console that works fully offline with Ollama. Plus `aec-bridge connect` config generation and a 10-minute non-developer install.
2. **Phase I added — Popularity Pack (I1–I8),** research-ranked by popularity × ease. Headline findings from the 2026-06 ecosystem scan: desktop Revit MCP is **commoditized** (Revit 2027 ships a built-in MCP server; many community servers exist); **BCF has zero MCP bridges anywhere** — an open killer-demo gap we can own; Archicad's Tapir JSON API makes that bridge nearly free; headless no-Blender IFC (which we already have) is itself a marketable wedge.
3. **Strategic position sharpened:** wrap, don't compete. The defensible "orchestration bed" is the **neutral coordination layer** — IFC + BCF + Speckle + clash + cross-tool identity + Run Records — that no vendor will build across competitors' tools. I8 (ADR 0006) encodes coexistence with Autodesk's own MCP servers; E5's APS work should wrap official Autodesk MCPs where they exist rather than re-implement.
4. **G1 (Archicad) promoted** from spec-only to implementation (I5).
5. **Early dispatch note:** I1 (BCF) depends only on A8 — it does not need to wait for Phases B–C and should be dispatched early; it is the cheapest high-visibility win in the whole backlog.
6. **Ralph loop made turnkey:** root `PROMPT.md` (loop prompt, re-read fresh every iteration) and `AGENT.md` (accumulated learnings file) now exist, so any loop runner can drive the backlog unattended.
7. **Performance posture decided (A11 → ADR 0007):** the hub stays **Python**; no C/Rust rewrite. Hub latency is dominated by the host applications (Revit API calls run on Revit's UI thread), network, and disk — not the interpreter — and the Python ecosystem (MCP SDK, IfcOpenShell, specklepy, ifctester, pyarrow/DuckDB) is the project's moat. The genuinely hot paths already execute in native code (IfcOpenShell's C++ core, Arrow/DuckDB). Escape hatch: a single profiled module may drop to Rust/C++ as a Python extension (PyO3), never a rewrite. The parts running *inside* the software are already native C# add-ins.

## 3. Chapter 2 thesis

Chapter 1 (Phases A–G) builds the machine: switches, contract, orchestrator, data plane, distribution. Chapter 2 makes the machine reachable: **any AI the user already has (Phase H) × the bridges most likely to spread by word of mouth (Phase I).** The end-state demo that proves the vision: a BIM coordinator with no developer tools installs the bridge in 10 minutes, connects it to whatever AI account they have (or a free local model), says "check this federated model and file the clashes," and gets a health score, a BCF file their team's tools can open, and a 3D viewer link they can email — across Revit, Navisworks, Rhino, Archicad, and plain IFC.

Phase ordering stays honest: H and I sit **after** their dependencies (policy B14, workflow tools C6, Run Records C7), not before — exposing 157 raw tools to the open internet without the policy layer would be the wrong kind of popular. The only Chapter 2 card safe to run early is I1 (BCF), plus the two ADRs (H1, I8) once B14's semantics are settled.

## 4. Dispatch kit (hand this section to building agents)

### Mode 1 — Ralph loop (one agent, sequential)

Run any loop harness against root `PROMPT.md`, e.g.:

```powershell
while ($true) { Get-Content PROMPT.md -Raw | claude -p --dangerously-skip-permissions }
```

The prompt enforces: one card per iteration, search-before-assume, no placeholders, verify-before-done, marker + Progress Log update, learnings appended to `AGENT.md`, commit per task on `task/<id>`. Babysit the first few loops and add guardrail lines to `PROMPT.md` when the agent misbehaves (tune the prompt, not the output).

### Mode 2 — GSD parallel lanes (multiple agents, worktrees)

One agent per lane in separate worktrees; lanes touch disjoint files (see lane table in `agent-task-plan.md` §0). Brief each agent with: `docs/agent-task-plan.md` + "work ONLY lane `<X>`, one card at a time, same rules as PROMPT.md". Suggested waves:

- **Wave 0 (now):** merge in-flight A1/A3/A5/A8 branches → dispatch A2, A4, A6, A7 (PY/DOCS) ∥ B1 ADR (DOCS) ∥ I1 BCF (PY).
- **Wave 1:** B2/B3/B12/B13/B14 (PY) ∥ B4→B5 (NET, split B4 first) ∥ B6→B9 (NET) ∥ F2 docs site (DOCS).
- **Wave 2:** C1→C8 (PY, mostly sequential) ∥ B10/B11/B15 ∥ F1 (NET) ∥ H1 + I8 ADRs (DOCS).
- **Wave 3:** C9–C12 recipes ∥ D1/D5 ∥ I2/I3/I4 ∥ H2→H3→H4 + H6.
- **Wave 4:** D2–D4 ∥ H5/H7/H8 ∥ I5/I6/I7 ∥ F3/F6/F7 ∥ E-phase ∥ G specs.
- **Human queue (anytime):** A9, A10, C13, E4/E5/E8 sub-steps, F5, H8 VM run.

### Short-form task index (one line per open card; full cards are canonical in `agent-task-plan.md`)

```text
A2  PY S  pin specklepy>=3,<4 and fix API drift
A4  PY S  register McpProxyProvider + MCP_PROXY_TARGETS Rhino pairing docs
A6  DOC S fix stale architecture/security docs ("25 tools" etc.)
A7  PY S  delete stray .3dm, gitignore build dirs, dist/ policy
A11 DOC S ADR 0007: Python-first perf posture + budgets + perf smoke test
B1  DOC M ADR 0002: Switch Contract v2 (registry file, tokens, /capabilities)
B2  PY M  discovery registry reader (scan, validate, prune, discover_switches)
B3  PY S  bearer-token client + legacy fixed-port fallback
B4  NET L Revit add-in: [BridgeCommand] attributes → /capabilities manifest
B5  NET M Revit add-in: dynamic port + token + registry file runtime
B6  NET M Navisworks: attribute command routing infrastructure
B7  NET M Navisworks routes: doc info, model tree, selection, append
B8  NET S Navisworks routes: saved viewpoints
B9  NET L Navisworks routes: Clash Detective (tests, run, paged results)
B10 NET S Navisworks: Contract v2 runtime (port from B5)
B11 PY M  NavisworksProvider + mock clash fixtures + tests
B12 PY S  aec_bridge_status diagnostic tool
B13 PY S  aec-bridge doctor CLI
B14 PY M  policy layer: allowed_tools, destructive gates, high-risk flag
B15 PY S  redaction + abuse-case test extension
C1  PY M  ADR 0003 + Pydantic recipe schema
C2  PY S  capability naming layer + resolve_capability()
C3  PY M  engine core: steps, bindings, job pipeline
C4  PY S  capability fallbacks + degradation records
C5  PY M  confirmation gates, idempotency keys, dry-run
C6  PY S  workflow_* MCP tools + progress notifications
C7  PY M  Run Record schema v1 + builder + runs/ output
C8  PY M  identity map → SQLite persistence + auto-registration
C9  PY M  recipe W1 concept-to-BIM (Rhino→Revit) mock e2e
C10 PY S  recipe W2 coordination loop (clash, fallback graph)
C11 PY M  recipe W3 model health (zero-switch IFC) mock e2e
C12 PY S  recipe W4 data-lake drop (Speckle/Parquet)
D1  PY M  Run Record → Parquet/DuckDB lake exporter
D2  DOC S lakehouse layout doc + 5 DuckDB queries
D3  BI  M Power BI template: model health
D4  BI  M Power BI template: coordination
D5  PY M  ifc_validate_ids via ifctester + fixtures
D6  PY M  completion webhooks (Teams/Slack cards)
D7  PY S  graph_export_graphml
E1  PY M  Excel headless provider (openpyxl tables, sandboxed)
E2  PY M  excel_diff_table + gated write-back
E3  PY M  recipe W5 QTO round-trip mock e2e
E4  PY L  Excel via Microsoft Graph (OAuth)
E5  PY M  APS AEC Data Model GraphQL reads
E6  PY M  acc_create_issue + W2 publish_issues: acc
E7  PY M  ACC webhooks → auto-trigger recipes
E8  PY M  Solibri spike → ADR 0004 (REST vs plugin vs file-exchange)
E9  ?? L  Solibri switch per ADR 0004
E10 PY S  Solibri findings into W3 health score
F1  NET M switch SDK template (csharp echo switch)
F2  DOC M MkDocs site + GitHub Pages deploy
F3  DOC M zero-switch 10-min tutorial + aec-bridge demo
F4  PY/NET M release automation per switch + checksums
F6  BI  S  samples/ pack (IFC, massing, recipes, baked lake)
F7  DOC S  README rewrite around orchestration story
F8  DOC S  Rhino native plugin ADR (proxy-first verdict)
G1  PY M  Archicad Tapir spike (impl promoted to I5)
G2–G7 DOC S spec cards: Tekla, SketchUp, iTwin, Trimble, Procore, P6
H1  DOC M ADR 0005: four-door access layer + key/scope model
H2  PY M  remote MCP endpoint (Streamable HTTP) + API keys
H3  PY M  REST facade + generated OpenAPI + GPT-Action/n8n howto
H4  PY S  aec-bridge connect: per-client config generator
H5  PY L  BYO-LLM chat console (OpenAI-compatible incl. Ollama)
H6  PY M  workflow_validate + recipe JSON Schema + authoring prompt
H7  PY M  remote hardening: bind policy, rate limits, key rotation
H8  PY/NET M one-line Windows install → doctor → connect (≤10 min)
I1  PY M  BCF 2.1/3.0 provider (read/write topics+viewpoints) ← EARLY, only needs A8
I2  PY S  W2 clash → BCF publishing (killer demo)
I3  PY M  IFC→glTF + self-contained HTML viewer artifact
I4  PY S  aec_describe_model LLM-ready digest
I5  PY M  Archicad provider via Tapir schema-generated tools
I6  PY M  gh_run_definition via Rhino.Compute
I7  PY M  drop-folder watcher → auto-run recipe
I8  DOC M ADR 0006: Revit 2027 built-in MCP coexistence (wrap, don't compete)
HUMAN: A9 licensing · A10 repo rename · C13 live runs · E4/E5/E8 accounts · F5 App Store · H8 VM evidence
```

### Rules every dispatched agent must follow

The 10 Standing Rules in `agent-task-plan.md` §2, plus the loop discipline baked into `PROMPT.md`: one card per run · search the codebase before assuming something is missing · no placeholder or stubbed implementations · the card's Verify command must pass before marking `[x]` · append non-obvious learnings to `AGENT.md` · commit per task, never to `main`.

## 5. Critical path

A-merge → B1 → B2/B14 → C1→C6/C7 → (C9–C12 ∥ H1→H2/H3) → H5/H8 + I2/I3. Everything else hangs off this spine in parallel lanes. The two cards most likely to need splitting before dispatch: B4 (annotate ~103 routes) and H5 (console UI).

---

**Changelog**

- 2026-06-13 — v1.0 — Chapter authored from the 2026-06-13 program review + ecosystem research; companion to agent-task-plan v1.1.
