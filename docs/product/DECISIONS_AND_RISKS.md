# Decisions & Risks Log

Append-only. Decisions carry status: **Decided** (by Sam) / **Proposed** (needs Sam) / **Open**.

## Decisions

| ID | Decision | Status | Rationale |
|---|---|---|---|
| D-001 | Product name = **AEC Model Bridge**; "Omni-Bridge" = legacy/ecosystem narrative only | **Decided** 2026-07-08 | Matches repo slug, PyPI, server.json; ends 4-name chaos |
| D-002 | MVP = inspect (W1) → QA/QC (W7/W9) → parameters (W5); **façade roundtrip deferred** to Phase-2 flagship | **Decided** 2026-07-08 | Three workflows share one semantic layer; façade proves it publicly afterwards |
| D-003 | MVP audience = **normal Revit users**; dockable WebView2 panel + approval queue in first release | **Decided** 2026-07-08 | Product differentiation is the safety UX, not the tool count |
| D-004 | One hub server: `mcp_server.py`; retire `server.py` + legacy `tools/`/25-tool system after test migration | Proposed | Two servers with divergent providers/env vars confuse everything; `server.py` has a known `_connect()` bug |
| D-005 | Revit targets: **net48 (2024) + net8 (2025/26)** shipped; net10 (2027) experimental | **Decided** 2026-07-08 | Multi-target already in csproj; broadest firm reach |
| D-006 | Contract v2 (dynamic port + bearer) becomes **runtime default**; legacy :3000 opt-in | Proposed | Unauthenticated default contradicts the safety story; ADR 0002 already accepted |
| D-007 | Approval gate enforced in the **hub** (single choke point), C# `ConfirmationRequired` stays defense-in-depth | Proposed | One enforcement point across all switches; direct-HTTP callers still guarded |
| D-008 | Panel UI = WebView2-hosted web app, WPF only as pane chrome | Proposed | Iteration speed; reusable across hosts; spike memory/load-order in P16.1 first |
| D-009 | Power BI: **file lane first** (SQLite→.pbit); live ADOMD lane wired health-only until pulled | Proposed | External-tool session handshake is fragile; file lane delivers value now |
| D-010 | Hub install for non-programmers: bundled Python runtime in installer (pipx as expert path) | Open | Decide at P19; bundled ≈ +80 MB but zero-friction |
| D-011 | Dead C# tree `src/Commands/**`: delete after per-subsystem salvage review | Open — needs Sam | 0 registered commands, compile-excluded; keeping it misleads every future agent |
| D-012 | CI Revit e2e: self-hosted runner vs scripted-local-only | Open | Depends on Sam's hardware/licensing; goldens must run *somewhere* nightly |
| D-013 | Git history rewrite to purge 92 MB binaries (BFG) vs plain `git rm` | Open — needs Sam | Rewrite breaks clones/forks; rm leaves history heavy |
| D-014 | Docs package lives in `docs/product/`, monetization content excluded (private doc moves out, P0.2) | **Decided** 2026-07-08 | Public-repo hygiene |

## Risks

### Revit API
- **R1 Threading/deadlock:** all writes must ride the existing ExternalEvent queue; any new code path that touches the API off-thread crashes Revit. *Mitigation:* single choke point (`RevitCommandExecutor`), reviewed by Security/Safety agent; no async API access ever.
- **R2 Snapshot perf on big models:** 100k+ elements × params is minutes, not seconds. *Mitigation:* incremental extraction via `DocumentChanged` dirty-list (P3.4), category filtering, measure before optimizing (ADR 0007 budgets).
- **R3 Multi-target drift:** net48 vs net8 API differences (nullable, some API changes 2024→2025). *Mitigation:* CI builds both; `#if` islands kept minimal; Nice3point packages per version.
- **R4 Worksharing:** writes to elements owned by others fail mid-plan. *Mitigation:* ownership check at plan time; partial-apply policy = report-and-continue with explicit summary (never silent).

### MCP
- **R5 Tool-count bloat (~170+):** agents pick wrong tools. *Mitigation:* metadata + module namespacing; curated tool subsets per surface; snapshot-first querying reduces call volume.
- **R6 MCP SDK churn** (`mcp>=0.9.0`): breaking spec changes. *Mitigation:* pin + contract tests; adapter layer is thin.
- **R7 Breaking the shipped surface:** renames strand existing users. *Mitigation:* additive-only within 1.x; renames need human approval (swarm rule).

### Plugin app
- **R8 WebView2 in Revit process:** memory pressure, runtime missing, load-order clashes with other add-ins. *Mitigation:* P16.1 spike before committing; WPF fallback documented as plan B.
- **R9 Installer/AV friction:** unsigned DLLs + local HTTP server look suspicious. *Mitigation:* code-signing cert (P19), loopback-only listener, clear firewall docs.

### Semantic data
- **R10 Schema churn after freeze:** downstream (rules, panel, exporters) all break. *Mitigation:* append-only within major; `schema_version` everywhere from first byte.
- **R11 UniqueId edge cases:** SaveAs, detach, IFC re-export change identity anchors. *Mitigation:* doc-guid anchoring + re-anchor prompt (W9); mapper keeps provenance.

### AI agents
- **R12 Silent mutation = product death.** One incident of an AI changing a model without approval kills trust permanently. *Mitigation:* gate default-on, `approve_plan` not callable by agents on panel surface, audit ledger, `agent_reviewer` second-model check (P2 tier). **This is the risk the whole architecture exists to kill.**
- **R13 Query hallucination:** wrong answers about the model are almost as bad. *Mitigation:* DSL-validated `snapshot_query` is the only query path; answers cite element uids; golden Q&A tests.
- **R14 Swarm merge conflicts / context loss:** *Mitigation:* path ownership, contract freezes, worktrees, handover format (swarm plan).

### Integrations
- **R15 Version matrices** (Rhino×RiR×Revit, Dynamo×Revit, PBI sessions): support cost explodes. *Mitigation:* pinned supported matrix per release; everything else "community-tested".
- **R16 OAuth secrets/tokens** (Speckle/APS) on disk. *Mitigation:* existing redaction + OS credential store at P20; never in workspace exports.

### Performance
- **R17 Chat context flooding:** dumping element lists into LLM context. *Mitigation:* payload caps, snapshot files + summaries, uid-chip pattern.

### Security
- **R18 Unauthenticated legacy port** during transition (today's default!). *Mitigation:* D-006 flip early (P3.1); loopback-only binding already in place.
- **R19 `*_execute_python` / reflection escape hatches** bypass all semantics. *Mitigation:* `python.host` permission, expert-mode only, off by default, always audited.
- **R20 Third-party modules run arbitrary code.** *Mitigation:* trust-model doc, explicit enable per module dir, firm allowlist (P20.1).

### Adoption
- **R21 "Another automation tool" skepticism + AI-in-production fear.** *Mitigation:* the demo arc leads with approval/rollback, not with AI magic; read-only workflows first in every firm rollout.
- **R22 Solo-maintainer bus factor / burnout.** *Mitigation:* the swarm plan and this package *are* the mitigation — any capable agent session can resume from `NEXT_AGENT_HANDOVER.md`.

## Open questions

1. D-010/D-011/D-012/D-013 need Sam's call (installer runtime, dead tree, CI runner, history rewrite).
2. Which Revit version is on Sam's machine right now? (Determines the first e2e loop; multi-target can compile blind but e2e cannot.)
3. Panel LLM plumbing for non-Claude-Code users: MVP assumes Claude Code/desktop as the agent host — does v1.3.0 need an embedded API-key client, or is "bring Claude" acceptable for first release?
4. Rule pack authorship: which 15 rules does Sam's project experience rank highest? (P10.2 review gate.)
5. Canonical test model style: generic office tower vs façade-heavy tower (dual-purpose for P11 demo)?
