# AEC Omni-Bridge — Agent Task Plan (Master Scaffolding Backlog)

**Status:** Living execution backlog (v1.1, 2026-06-13)
**Companion docs:** `docs/system-blueprint-and-workflows.md` (the architecture — canonical), `docs/agent-handover-prompt.md` (dispatch context), ADR 0001.
**Purpose:** Decompose the road from the current verified state (blueprint §0) to the **Ultimate State** (§1 below) into small, independently verifiable tasks that can be delegated to coding agents one at a time (Ralph-style loop) or in parallel lanes (GSD-style dispatch).

---

## 0. How to Use This Document

### Task states
Every task title starts with a state marker. Agents must update it when they finish:

- `[ ]` — open, may be picked up if all dependencies are `[x]`
- `[~]` — in progress (add agent/branch name)
- `[x]` — done (append: date · evidence, e.g. test command output summary or commit hash)
- `[B]` — blocked (append one line: exactly what is missing; never guess past a blocker)
- `[H]` — requires the human (license purchase, vendor account, legal review, store submission)

### Dispatch mode 1 — Ralph loop (one agent, one task per iteration)
Paste this prompt to the agent (or into the loop runner) verbatim:

```text
You are an implementation agent for AEC Model Bridge.
1. Read docs/agent-task-plan.md. Read docs/system-blueprint-and-workflows.md
   sections referenced by the task you select.
2. Select the FIRST task in the earliest active phase whose marker is [ ] and
   whose "Depends on" tasks are all [x]. Skip [H] tasks — those are human-only.
3. Complete that ONE task fully: implement, write the tests the card demands,
   run the Verify command(s), and make them pass.
4. Update the task marker in docs/agent-task-plan.md to [x] with today's date
   and one evidence line. If you could not finish, mark [~] or [B] with a
   one-line reason.
5. Commit with message "<task-id>: <summary>" on a branch named task/<task-id>.
6. Obey every Standing Rule in section 2. Then STOP. One task per run.
```

### Dispatch mode 2 — GSD parallel lanes (multiple agents, worktrees)
Tasks are tagged with a **Lane**. Tasks in different lanes touch disjoint files and may run in parallel worktrees safely. Tasks in the same lane run sequentially. Map to your GSD planning: Phase = goal, Epic = project, task card = next-action (each card carries its own context and done-definition, so it is dispatchable without extra briefing).

| Lane | Territory | Typical agent |
| --- | --- | --- |
| **PY** | `packages/mcp-server-revit/**` (Python hub) | Python-capable agent |
| **NET** | `packages/revit-bridge-addin/**`, `packages/navisworks-bridge-addin/**`, future C#/Java switches | .NET-capable agent on Windows |
| **DOCS** | `docs/**`, `README.md`, docs site | Any agent |
| **DATA** | Power BI templates, lakehouse layout, sample assets | BI-capable agent or human |
| **HUMAN** | Legal, vendor accounts, store submissions, live licensed-software runs | You |

### Sizing
**S** ≤ ~2 h of agent work · **M** ≤ ~1 day · **L** = multi-day (cards marked L should usually be split further by the agent before starting — splitting is allowed, deleting scope is not).

---

## 1. Definition of the Ultimate State (what "done" means for the whole program)

The program is complete when ALL of the following are true:

1. **Switches** (each independently installable, Contract v2 compliant — blueprint §3):
   Revit ✦ Navisworks ✦ Rhino (proxy + optional native plugin) ✦ Solibri ✦ Excel (headless + Graph) ✦ Speckle ✦ ACC/Forma — live; Archicad/Tekla/SketchUp/iTwin/Trimble/Procore/P6 have decision-ready specs (Phase G).
2. **Orchestrator:** declarative recipe engine with fallbacks, confirmation gates, idempotency, progress notifications; flagship recipes W1–W5 pass mock-mode e2e in CI and have recorded live-run evidence.
3. **Provenance:** every run emits a versioned Run Record (blueprint §5.2); identity map persisted per workspace.
4. **Data plane:** Speckle commits + local Parquet/DuckDB lakehouse; two published `.pbit` Power BI templates work against the Run Record schema.
5. **Security:** per-session tokens, dynamic ports, discovery registry, policy layer (allow-list, destructive gates), redaction tests for every provider.
6. **Distribution:** per-switch release packages with checksums, docs site with generated tool catalog, zero-switch IFC demo as the first-run tutorial.
7. **No doc describes anything that does not exist.** (The §0 baseline discipline, permanent.)
8. **Any-AI access (Chapter 2):** the hub is drivable from whatever AI the user already has — MCP stdio, remote MCP (Streamable HTTP) with per-key auth, a REST/OpenAPI facade, and a bundled bring-your-own-LLM console (incl. fully offline via Ollama); a non-developer installs and connects in ≤10 minutes.
9. **Neutral-layer bridges (Chapter 2):** BCF in/out (clash → issues any tool can open), IFC→glTF shareable web viewer, model digest for LLMs, Archicad (Tapir), Grasshopper definition runner, drop-folder automation — the coordination layer no vendor builds across competitors' tools.

---

## 2. Standing Rules (binding on every agent, every task)

1. **Back-compat is sacred:** existing `revit_*` MCP tool names, `revit.*` bridge routes, and `MCP_REVIT_*` env vars keep working. Regression = failed task.
2. **Mock-first:** every feature must be testable in CI without licensed software. Live tests go behind explicit env flags (`AEC_LIVE_TESTS=1`) and are excluded from default pytest runs.
3. **No vendor SDK binaries in the repo.** Reference assemblies installed with the host product (as the Revit/Navisworks csproj files already do).
4. **Secrets and tokens never appear** in tool args, results, logs, code, or commits. Extend `security/audit.py` redaction tests for anything new.
5. **Manifests over hand-written catalogs:** new tools must be described by capability manifests; docs are generated (task A5).
6. **One ADR per architectural decision**, numbered sequentially in `docs/`, amending — never silently contradicting — the blueprint.
7. **Verify before done:** the card's Verify command(s) must pass. Paste a one-line result summary as evidence. Python tests: `python -m pytest packages/mcp-server-revit/tests`. Add-in builds: `.\scripts\build-addin.ps1 -RevitVersion <year> -Configuration Release`.
8. **PowerShell 5.1 syntax** in any scripts (no `&&`, no ternary).
9. **If a card's instructions contradict reality** (file moved, API changed), follow reality, note the discrepancy in the evidence line, and update the card text.
10. **Conventional commits**, task ID prefixed. Never commit directly to `main`.

---

## 3. Switch Inventory — every connector needed for the Ultimate State

| Software | Connector type | Add-in/plugin required? | Status today | Built by tasks |
| --- | --- | --- | --- | --- |
| **Revit** | Desktop switch, C# add-in, loopback HTTP | Yes — **exists** (2024–2027) | Operational; needs Contract v2 upgrade | B4, B5 |
| **Navisworks Manage** | Desktop switch, C# add-in | Yes — **exists as stub** | `/health` only; no clash routes; no Python provider | B6–B11 |
| **Rhino/Grasshopper** | (a) SSE proxy to an existing Rhino MCP plugin; (b) Rhino.Compute provider; (c) optional own `.rhp` | (a) no — reuse; (c) yes, optional | Compute provider registered; proxy broken/unregistered | A3, A4, F8 |
| **Solibri Office** | Desktop switch via Solibri REST API (local, enabled with `--rest-api-server-port`, default 10876 — verify current docs) or Java Open API plugin; fallback: IFC-in/BCF-out file exchange | Possibly (Java plugin) — decided by spike | Not started | E8–E10 |
| **Excel (local)** | Headless switch inside hub (openpyxl) | No | Not started | E1–E3 |
| **Excel (SharePoint/OneDrive)** | Cloud provider via Microsoft Graph | No | Not started | E4 |
| **Speckle** | Cloud provider (OAuth PKCE, GraphQL) | No | Operational, needs consolidation | A1, A2 |
| **ACC / Forma (APS)** | Cloud provider (APS OAuth) | No | 12 tools exist; needs AEC Data Model + Issues | E5–E7 |
| **IFC (IfcOpenShell)** | Headless, in-hub | No | Operational | D5 extends |
| **Archicad** | Hub-side provider over Archicad's local JSON API (default port 19723 — verify) — **no add-in needed** | No | Spec only | G1 |
| **Tekla Structures** | Desktop switch, .NET local adapter | Yes | Spec only | G2 |
| **SketchUp** | Desktop switch, Ruby extension | Yes | Spec only | G3 |
| **iTwin / Trimble Connect / Procore / P6** | Cloud providers | No | Spec only | G4–G7 |

---

## 4. Milestone Map

```text
PHASE A (hygiene)──► PHASE B (Contract v2 + Navisworks + policy)──► PHASE C (orchestrator + recipes)
                                                                        │
        PHASE F (docs site, SDK template, releases) ◄── partially parallel from A5/B1
                                                                        ▼
                                            PHASE D (data plane + Power BI)──► PHASE E (Excel, ACC, Solibri)
                                                                        │
                                                            PHASE G (Wave-3 specs, anytime after C)
                                                                        │
            CHAPTER 2:  PHASE H (any-AI access layer) ◄── after B14/C6 ─┤
                        PHASE I (popularity pack: BCF, viewer, digest,  │
                                 Archicad, Grasshopper, watcher) ◄──────┘
```

**Phase gates:** a phase is closed when all its non-`[H]` tasks are `[x]` and the gate check listed at the end of the phase passes.

---

## PHASE A — Truth & Hygiene

> Goal: the codebase matches its documentation; known defects from blueprint §9 are fixed. Mostly Lane-PY.

#### [x] A0 — Author canonical blueprint + rewrite handover prompt
Done 2026-06-12 · `docs/system-blueprint-and-workflows.md`, `docs/agent-handover-prompt.md`, strategy doc created.

#### [~] A1 — Consolidate Speckle to a single provider *(dispatched: codex/gpt-5.4, branch task/A1-speckle, 2026-06-12)*
- **Lane:** PY · **Size:** M · **Depends on:** —
- **Context:** `providers/speckle.py` (orphaned, 2 tools), `providers/cloud.py` (registered, 14 tools), `mcp_server.py`, `tests/test_cloud_providers.py`.
- **Do:** Port anything uniquely useful from `speckle.py` (the simple `send_data` convenience using Speckle Manager's `get_default_account()` is worth keeping as a zero-OAuth fast path) into `cloud.py` as `speckle_send_object` / `speckle_receive_object`; fix the bug where model *name* is passed as `model_id` (resolve name → ID via a models query first); replace error-strings-as-results with raised typed exceptions; delete `providers/speckle.py`.
- **Done when:** one Speckle provider exists; name→ID resolution covered by a unit test; receive path deserializes data (not just member names).
- **Verify:** `python -m pytest packages/mcp-server-revit/tests -k "speckle or cloud"`

#### [ ] A2 — Fix specklepy dependency pin
- **Lane:** PY · **Size:** S · **Depends on:** A1
- **Do:** In `packages/mcp-server-revit/pyproject.toml` change `specklepy>=2.17.0` to `specklepy>=3,<4`; run the Speckle test suite against the installed 3.x; fix any API drift found.
- **Verify:** fresh `pip install -e packages/mcp-server-revit[dev]` resolves specklepy 3.x; Speckle tests pass.

#### [~] A3 — Fix McpProxyProvider connect lifecycle *(dispatched: codex/gpt-5.4, branch task/A3-proxy, 2026-06-12)*
- **Lane:** PY · **Size:** M · **Depends on:** —
- **Context:** `providers/proxy.py` — `_connect()` exists but is never called; `_connected` stays `False`; every `execute_tool` raises.
- **Do:** Add an async `initialize()` (or lazy first-call connect) that establishes the SSE session; add reconnect-with-backoff on dropped connections; surface remote tool list into the capability manifest; add unit tests with a fake SSE server.
- **Done when:** a fake MCP server's tools are callable through the proxy in tests, including one disconnect/reconnect cycle.
- **Verify:** `python -m pytest packages/mcp-server-revit/tests -k proxy`

#### [ ] A4 — Register the proxy provider + Rhino pairing config
- **Lane:** PY · **Size:** S · **Depends on:** A3
- **Do:** Register `McpProxyProvider` in `mcp_server.py` inside a try/except (absent → warning, like other optional providers); config via `MCP_PROXY_TARGETS` (e.g. `rhino=http://localhost:9876/sse`); document the pairing with an external Rhino MCP plugin in `docs/configuration-reference.md` and README (replacing the currently inaccurate `:9876` claim).
- **Verify:** proxy tools appear in `list_tools()` when a fake target is configured in tests; absent target degrades to a logged warning.

#### [~] A5 — Generated tool catalog *(dispatched: codex/gpt-5.4, branch task/A5-catalog, 2026-06-12)*
- **Lane:** PY (generator) + DOCS (output) · **Size:** M · **Depends on:** —
- **Do:** Add a script (e.g. `packages/mcp-server-revit/scripts/generate_tool_docs.py`) that introspects the provider registry and writes `docs/tools-generated.md`: one section per provider, one row per tool (name, description, mutating?, sync/async). Wire into CI as a drift check (regenerate + `git diff --exit-code`). Mark the old hand-written `docs/tools.md` as legacy with a banner pointing at the generated file.
- **Verify:** CI step passes; generated file lists all ~155 tools across 9 providers.

#### [ ] A6 — Correct stale architecture docs
- **Lane:** DOCS · **Size:** S · **Depends on:** A5
- **Do:** Fix `docs/architecture.md` ("25 tools" claim and any single-provider framing); align `docs/security.md` so unimplemented config keys are clearly marked "planned — see task B14" until B14 lands.
- **Verify:** grep for "25 tools" returns nothing; docs review.

#### [x] A7 — Repo hygiene (2026-06-13 · files already deleted, .gitignore updated, tests pass)
- **Lane:** PY · **Size:** S · **Depends on:** —
- **Do:** Delete `docs/Untitled.3dm` + `docs/Untitled.3dm.rhl`; add `.gitignore` entries for `packages/*/build/`, `packages/*/.venv/`; decide and document `dist/` policy (recommend: remove from git, attach to GitHub Releases only — record decision in `CONTRIBUTING.md`). Note: 3dm files were already missing in reality.
- **Verify:** `git status` clean after build; repo size reduced; CI green.

#### [~] A8 — Parameterized provider contract tests *(dispatched: codex/gpt-5.4, branch task/A8-contract-tests, 2026-06-12)*
- **Lane:** PY · **Size:** M · **Depends on:** —
- **Context:** `providers/fake.py` and existing `tests/test_providers.py`.
- **Do:** Build one pytest suite parameterized over every registered provider asserting the contract: identity is stable; every manifest tool has valid input schema; unknown tool → typed error; manifest `is_mutating` flags exist; results survive `redact_data` without leaking paths/tokens.
- **Verify:** `python -m pytest packages/mcp-server-revit/tests -k contract` covers ≥9 providers.

#### [H] A9 — Licensing review for non-Revit switches
- **Lane:** HUMAN · **Size:** M · **Depends on:** —
- **Do (you):** Obtain a written position on GPL linking exceptions for Navisworks (already shipped — retroactive), Rhino, Solibri, Tekla. Decide per-connector exceptions vs a generalized host-application exception. Record in `LICENSING.md` + new exception file(s).
- **Done when:** position documented; blocking ambiguity removed for E8–E10 and F5.

#### [H] A10 — Repo rename to `aec-model-bridge` (blueprint OD5)
- **Lane:** HUMAN · **Size:** S · **Depends on:** —
- **Do (you):** Rename on GitHub (auto-redirect preserves old links); update badge URLs, clone URLs, MCP registry entry.

#### [x] A11 — ADR 0007: hub performance posture (2026-06-13 · test_perf passed)
- **Lane:** DOCS+PY · **Size:** S · **Depends on:** —
- **Do:** Record the language/runtime decision so no agent drifts into a rewrite: the hub stays **Python** — the ecosystem is the moat (MCP SDK, IfcOpenShell, specklepy, ifctester, openpyxl, pyarrow/DuckDB), and hub latency is dominated by host applications and network/disk I/O, not the interpreter. Rules: performance-critical paths must use native-backed libraries (IfcOpenShell's C++ core for geometry, pyarrow/DuckDB for the lake, `orjson` for large payloads); a single module may be dropped to Rust/C++ as a Python extension (PyO3/nanobind) ONLY when a recorded profile shows it dominating a workflow budget — never a whole-hub rewrite. Desktop switches remain native by construction (C# in-process with each host). Define budgets in the ADR: hub tool-dispatch overhead < 10 ms; W3 health audit on the sample IFC < 60 s on a laptop. Add one perf smoke test (skip-by-default marker) asserting the dispatch-overhead budget.
- **Verify:** ADR merged with budgets table; `python -m pytest packages/mcp-server-revit/tests -k perf -m perf` passes locally.

**Phase A gate:** CI green; `pytest` full suite passes; one Speckle provider; proxy registered; generated catalog live; A9 position recorded.

---

## PHASE B — Switch Contract v2, Navisworks Completion, Policy Layer

> Goal: secure modular discovery (blueprint §3), a real Navisworks switch, and the policy gates. Lanes PY and NET run largely in parallel after B1.

#### [x] B1 — ADR 0002: Switch Contract v2 specification (2026-06-13 · ADR merged)
- **Lane:** DOCS · **Size:** M · **Depends on:** —
- **Do:** Write `docs/0002-switch-contract-v2.md` finalizing: registry file JSON schema (path `%LOCALAPPDATA%\AECModelBridge\registry\<provider>-<pid>.json`; fields per blueprint §3.3), token rules (generation, ACL, header `Authorization: Bearer`), `/capabilities` manifest schema (reuse ADR 0001 §3), protocol_version=2 negotiation, legacy fixed-port fallback + deprecation timeline, stale-entry pruning rules (PID liveness + max age).
- **Done when:** ADR merged; both PY and NET lanes can implement from it without further decisions.

#### [ ] B2 — Hub: discovery registry reader
- **Lane:** PY · **Size:** M · **Depends on:** B1
- **Do:** New module (e.g. `bridge/discovery.py`): scan registry dir, validate schema, check PID liveness, prune stale files, expose `discover_switches()`; integrate into provider initialization so desktop providers resolve endpoint+token dynamically; env override `MCP_REVIT_BRIDGE_URL` still wins (back-compat).
- **Verify:** unit tests with temp registry dirs: valid entry, stale PID, malformed JSON, ACL-denied file.

#### [ ] B3 — Hub: bearer-token client + legacy fallback
- **Lane:** PY · **Size:** S · **Depends on:** B2
- **Do:** `BridgeClient` sends the discovered session token; on no registry entry, probe legacy `:3000`/`:3002` tokenless with a deprecation warning logged once. Tokens excluded from logs/audit (extend redaction tests).
- **Verify:** tests: token attached; legacy path warns; token never in audit log fixture.

#### [ ] B4 — Revit add-in: capability manifest generation
- **Lane:** NET · **Size:** L (split allowed) · **Depends on:** B1
- **Context:** `src/Bridge/BridgeCommandFactory.cs` (~103 route switch).
- **Do:** Introduce a `[BridgeCommand(Name, IsMutating, ConfirmationRequired, ExecutionMode)]` attribute; annotate handlers (mechanical but large — split by command registry file); build factory routing AND `/capabilities` JSON from the attributes at startup. The switch expression goes away; one source of truth.
- **Done when:** `GET /capabilities` returns all routes with correct mutating flags; route count matches pre-refactor (regression-tested by comparing route lists).
- **Verify:** `.\scripts\build-addin.ps1 -RevitVersion 2026 -Configuration Release`; route-parity test.

#### [ ] B5 — Revit add-in: Contract v2 runtime (port, registry file, token)
- **Lane:** NET · **Size:** M · **Depends on:** B4
- **Do:** Bind OS-assigned loopback port (config override to pin 3000 for legacy clients, default ON for one release); generate session token; write/delete registry file on startup/shutdown (and on crash: stale-file tolerance is B2's job); enforce token on `/execute` (skip when legacy fixed-port mode is active); add request size + concurrency limits.
- **Verify:** build all four Revit targets; manual smoke: `Invoke-RestMethod` health with and without token.

#### [ ] B6 — Navisworks add-in: command routing infrastructure
- **Lane:** NET · **Size:** M · **Depends on:** B1
- **Context:** `packages/navisworks-bridge-addin/src/` — currently `/execute` returns doc title only.
- **Do:** Mirror the Revit add-in's pattern at small scale: attribute-based command registry (same design as B4 from day one — no switch-expression detour), main-thread execution guard (Navisworks API calls must run on the UI thread — use the plugin's synchronization context), result envelope per blueprint §3.2.
- **Verify:** builds for net48 + net8.0-windows; a `navis.echo` test command round-trips.

#### [ ] B7 — Navisworks routes: model tree, selection, append/refresh
- **Lane:** NET · **Size:** M · **Depends on:** B6
- **Do:** Routes: `navis.get_document_info`, `navis.get_model_tree` (depth-limited, with item paths + GUIDs where present), `navis.get_selection`, `navis.append_file`, `navis.refresh`. Use `Autodesk.Navisworks.Api` Document/Models/ModelItem APIs.
- **Verify:** build passes; route list includes the five; manual smoke against a sample NWD recorded in evidence.

#### [ ] B8 — Navisworks routes: saved viewpoints
- **Lane:** NET · **Size:** S · **Depends on:** B6
- **Do:** `navis.list_viewpoints`, `navis.create_viewpoint`, `navis.activate_viewpoint` (SavedViewpoints API).
- **Verify:** build; smoke evidence.

#### [ ] B9 — Navisworks routes: Clash Detective
- **Lane:** NET · **Size:** L · **Depends on:** B6
- **Do:** Routes: `navis.list_clash_tests`, `navis.create_clash_test` (two selection sets by model/path), `navis.run_clash_test`, `navis.get_clash_results` (grouped; per clash: status, distance, point, both item identities — path + IFC GUID property when available). Use `Autodesk.Navisworks.Api.Clash` (`DocumentClash.TestsData`, run via `TestsRunTest…`). Results may be large → support paging params.
- **Done when:** a two-model clash test runs and returns identifiable items end-to-end via HTTP.
- **Verify:** build; live smoke against Navisworks Manage with a sample federated model — record version + date.

#### [ ] B10 — Navisworks add-in: Contract v2 runtime
- **Lane:** NET · **Size:** S · **Depends on:** B5 (reuse its implementation), B6
- **Do:** Port the B5 port/registry/token/capabilities code (extract shared source or copy with attribution — no shared binary between add-ins to keep installs independent).
- **Verify:** registry file appears on plugin load; token enforced.

#### [ ] B11 — Hub: NavisworksProvider + mock + tests
- **Lane:** PY · **Size:** M · **Depends on:** B2 (discovery), B7–B9 (route shapes from ADR/B-lane PRs — can start from the ADR contract before NET lane finishes)
- **Do:** New `providers/navisworks.py` exposing `navisworks_*` tools mapping 1:1 to B7–B9 routes; `MockNavisworksBridge` with deterministic clash fixtures; register in `mcp_server.py` (optional-provider pattern); contract tests via A8 suite.
- **Verify:** `python -m pytest packages/mcp-server-revit/tests -k navisworks` (mock mode, no Navisworks needed).

#### [ ] B12 — Hub tool: `aec_bridge_status`
- **Lane:** PY · **Size:** S · **Depends on:** B2
- **Do:** One tool reporting every known switch: installed/alive/version/protocol/capability digest, plus "what installing X would unlock" (from a static capability→workflow map). This is the diagnostic entry point (blueprint §4.3).
- **Verify:** unit test over fake registry states (all-alive, one-stale, none).

#### [ ] B13 — CLI: `aec-bridge doctor`
- **Lane:** PY · **Size:** S · **Depends on:** B12
- **Do:** Console entry point (add to `pyproject.toml [project.scripts]`) wrapping B12 for humans: colorized table, exit code 0/1, install-pointer URLs for missing switches.
- **Verify:** `aec-bridge doctor` runs in a clean venv; snapshot test of output.

#### [ ] B14 — Policy layer (close the security.md gap)
- **Lane:** PY · **Size:** M · **Depends on:** A8
- **Do:** Implement in config + one enforcement point (registry execute path): `allowed_tools` allow-list, `allow_destructive` (default false → mutating tools refused with actionable message), `destructive_confirm` (require `confirm: true` arg on confirmation_required tools), `high_risk_enabled` (reflection/`execute_python` gated separately, default off). Update `docs/security.md` to describe reality.
- **Verify:** security tests: destructive call w/o opt-in refused; allow-list enforced; high-risk off by default.

#### [ ] B15 — Redaction & abuse-case test extension
- **Lane:** PY · **Size:** S · **Depends on:** B3, B14
- **Do:** Tests for: oversized request rejection, malformed manifest handling, stale discovery record, path traversal via workspace tools, token never present in any tool result or audit line (fuzz across providers).
- **Verify:** suite green; cases enumerated in evidence line.

**Phase B gate:** W2's switch-side prerequisites exist (clash runs via HTTP); `aec-bridge doctor` correctly reports a machine with only Revit installed; tokenless legacy mode warns; policy tests pass.

---

## PHASE C — Omni-Bridge Orchestrator & Flagship Recipes

> Goal: blueprint §5 — the recipe engine, Run Records, and recipes W1–W4 proven in mock mode, then live. Lane PY throughout; C-tasks are mostly sequential through C6, then C7–C12 parallelize.

#### [ ] C1 — ADR 0003: recipe engine & schema
- **Lane:** DOCS+PY · **Size:** M · **Depends on:** B-gate
- **Do:** Finalize blueprint §5.1 into `docs/0003-recipe-engine.md` + Pydantic models (`orchestrator/schema.py`): recipe doc (YAML authoring, JSON wire — blueprint OD1 leaning), step types (tool / capability / built-in), binding syntax (`$step_id.field`), `requires/prefer/fallback`, confirmation + idempotency semantics, error policy (fail-fast vs continue-with-degradation per step).
- **Verify:** schema round-trips the §5.1 example recipe; invalid recipes produce precise validation errors (tested).

#### [ ] C2 — Capability naming layer
- **Lane:** PY · **Size:** S · **Depends on:** C1
- **Do:** Add optional `capability` field to provider tool manifests (e.g. `revit_create_elements_batch` → `revit.create_elements`; `navisworks_run_clash_test` and `graph_audit_clashes` both → `clash`); registry API `resolve_capability(name) -> [tools ordered by preference]`.
- **Verify:** unit tests incl. multi-provider capability with preference order.

#### [ ] C3 — Engine core: step execution + bindings
- **Lane:** PY · **Size:** M · **Depends on:** C1, C2
- **Do:** `orchestrator/engine.py`: execute steps sequentially on the job pipeline (`workflow_run` returns a JobReference); resolve bindings; collect per-step results, warnings, artifacts into run state.
- **Verify:** 3-step recipe against FakeProvider passes e2e in tests.

#### [ ] C4 — Engine: capability fallbacks + degradation records
- **Lane:** PY · **Size:** S · **Depends on:** C3
- **Do:** When the preferred tool's provider is absent/unhealthy, fall through the C2 preference list; record each degradation (string per blueprint §5.2) in run state; if nothing resolves, fail the step with the "install X from URL" message pattern (B12's map).
- **Verify:** test with preferred provider removed → fallback used → degradation recorded.

#### [ ] C5 — Engine: confirmation gates, idempotency, dry-run
- **Lane:** PY · **Size:** M · **Depends on:** C3, B14
- **Do:** Steps marked `confirmation: required` pause the workflow (job status `awaiting_confirmation`, resumable via `workflow_confirm` tool); idempotency keys derived from `run_id + step_id` passed to mutating tools; `workflow_run(dry_run=true)` executes only read-only steps and emits the would-do plan for mutating ones.
- **Verify:** tests: paused→confirmed→resumed; duplicate run with same key is rejected by a FakeProvider asserting single execution; dry-run mutates nothing.

#### [ ] C6 — Workflow MCP tools + progress notifications
- **Lane:** PY · **Size:** S · **Depends on:** C3
- **Do:** Register `workflow_list`, `workflow_describe`, `workflow_run`, `workflow_status`, `workflow_confirm`, `workflow_cancel`; emit MCP progress notifications per step start/finish.
- **Verify:** tool-level tests; progress events observed in test harness.

#### [ ] C7 — Run Record schema v1 + builder
- **Lane:** PY · **Size:** M · **Depends on:** C3
- **Do:** Pydantic `RunRecord` per blueprint §5.2 (versioned, documented in `docs/run-record-schema.md` — generated from the model); builder collects switches/inputs/outputs/identity_map/degradations/artifacts; every workflow emits one; written to `<workspace>/runs/<run_id>.json`.
- **Verify:** schema doc generated; every engine test asserts a valid record.

#### [ ] C8 — Identity registry persistence + auto-registration
- **Lane:** PY · **Size:** M · **Depends on:** C3
- **Do:** Move `identity_mapper.py` store to SQLite per workspace (reuse exporter's SQLite plumbing — blueprint OD3); engine auto-registers mappings emitted by mutating steps (e.g. created Revit elements carrying source Rhino UUIDs); mappings appear in Run Records.
- **Verify:** mappings survive process restart in tests; W1 mock run populates the map.

#### [ ] C9 — Recipe W1: Concept-to-BIM (Rhino → Revit)
- **Lane:** PY · **Size:** M · **Depends on:** C4–C8
- **Do:** Author `recipes/concept-to-bim.yaml` per blueprint §6 W1; may require adding a `revit_create_elements_batch` hub tool composing existing bridge routes (create_wall/floor/column/level) with per-element idempotency; mock e2e test with fixture massing JSON.
- **Verify:** mock e2e in CI: fixture massing → ≥3 element categories in MockBridge → quantities in Run Record.

#### [ ] C10 — Recipe W2: Coordination Loop
- **Lane:** PY · **Size:** S · **Depends on:** C4–C8, B11
- **Do:** `recipes/coordination-loop.yaml`: append models → run clash (capability `clash`, prefer navisworks, fallback graph) → translate clash item IDs via mapper → Run Record.
- **Verify:** mock e2e both paths (Navisworks mock present; absent→graph fallback with degradation).

#### [ ] C11 — Recipe W3: Model Health & Compliance (zero-switch)
- **Lane:** PY · **Size:** M · **Depends on:** C4–C8 (IDS part arrives with D5 — score without IDS first)
- **Do:** `recipes/model-health.yaml`: IFC open → graph compile → audits (clashes, disconnected, load paths) → weighted health score (document the scoring rubric in the recipe) → Run Record. Must run with zero desktop software (blueprint §4.2).
- **Verify:** CI e2e against a committed sample IFC fixture produces a scored record.

#### [ ] C12 — Recipe W4: Data-Lake Drop
- **Lane:** PY · **Size:** S · **Depends on:** C7; Speckle path needs A1/A2; Parquet path needs D1 (either alone passes)
- **Do:** `recipes/data-lake-drop.yaml`: take any Run Record → Speckle version commit AND/OR Parquet write; either target alone is valid (blueprint §6 W4).
- **Verify:** mock e2e: record → fake transport commit; (after D1) → Parquet file readable.

#### [H] C13 — Live verification runs + evidence
- **Lane:** HUMAN (drives) + PY agent (fixes found issues) · **Size:** M · **Depends on:** C9–C12
- **Do (you):** Run W1 (Rhino+Revit live), W2 (Navisworks live), W3 (laptop, no Autodesk), W4 (real Speckle project + Parquet). Record host versions, dates, gaps in blueprint §10 C5 table. File defects as new tasks.

**Phase C gate:** all four recipes green in CI mock mode; live evidence recorded; `workflow_run` is the single entry point an MCP client needs for the hero demo.

---

## PHASE D — Data Plane & Dashboards

#### [ ] D1 — Parquet/DuckDB exporter for Run Records
- **Lane:** PY · **Size:** M · **Depends on:** C7
- **Do:** Extend `providers/exporter.py`: `exporter_run_to_parquet` flattening a Run Record into tables (`runs`, `elements`, `clashes`, `quantities`, `identity_map`) under `<workspace>/lake/`; append-mode so history accumulates; add `duckdb` + `pyarrow` as optional extra `[lake]`.
- **Verify:** tests: two runs → DuckDB query `SELECT count(*) FROM clashes GROUP BY run_id` returns both.

#### [ ] D2 — Lakehouse layout doc + history queries
- **Lane:** DOCS · **Size:** S · **Depends on:** D1
- **Do:** `docs/lakehouse.md`: directory layout, table schemas (generated from D1 models), five copy-paste DuckDB queries (clash trend, health score over time, quantities by category…), Power BI direct-Parquet import steps.

#### [ ] D3 — Power BI template: Model Health (W3)
- **Lane:** DATA · **Size:** M · **Depends on:** D1, C11
- **Do:** `.pbit` over the lake tables: health score trend, findings by severity, element counts. Ship in `templates/powerbi/` with a README and a sample lake generated from fixtures.
- **Done when:** template + one fixture Run Record → working dashboard in <10 min (blueprint D2 criterion).

#### [ ] D4 — Power BI template: Coordination (W2)
- **Lane:** DATA · **Size:** M · **Depends on:** D1, C10
- **Do:** `.pbit`: clash counts by test/status/run, new-vs-resolved trend, top clashing element pairs (via identity map).

#### [ ] D5 — IDS rule checking in IfcProvider
- **Lane:** PY · **Size:** M · **Depends on:** —(parallel any time)
- **Do:** Add `ifc_validate_ids(ifc_path, ids_path)` using the `ifctester` package (IfcOpenShell family); structured findings (spec, requirement, pass/fail, failing GUIDs); wire into W3's score; commit two sample IDS fixture files.
- **Verify:** tests against fixtures: one passing, one failing spec.

#### [ ] D6 — Completion webhooks (Teams/Slack)
- **Lane:** PY · **Size:** M · **Depends on:** C6
- **Do:** `webhook_register(url, events)` persisted per workspace; on workflow completion/failure POST an Adaptive Card (Teams) / Block Kit (Slack) summary of the Run Record; secrets-safe (URL stored, never echoed); retries with jitter.
- **Verify:** tests with a local HTTP capture server; payload snapshot tests.

#### [ ] D7 — GraphML export (optional, strategic roadmap item 4)
- **Lane:** PY · **Size:** S · **Depends on:** —
- **Do:** `graph_export_graphml(path)` on the semantic graph provider (networkx has native support); document the Neo4j import one-liner.

**Phase D gate:** the hero demo (W2/W3 → dashboard refresh shows new data within a minute) works via both the Speckle path and the local Parquet path.

---

## PHASE E — Wave 2 Switches: Excel, ACC/Forma, Solibri

#### [ ] E1 — Excel headless switch: core read/write
- **Lane:** PY · **Size:** M · **Depends on:** B14 (mutation gates)
- **Do:** New `providers/excel.py` (in-hub, openpyxl, optional extra `[excel]`): `excel_read_table`, `excel_write_table` (real Excel Tables/ListObjects, not bare ranges), `excel_list_sheets`; workspace-sandboxed paths only; mutating flags set.
- **Verify:** tests round-trip a table on a fixture workbook; sandbox violation refused.

#### [ ] E2 — Excel: dry-run diff + write-back
- **Lane:** PY · **Size:** M · **Depends on:** E1
- **Do:** `excel_diff_table` producing a cell-level JSON diff (the W5 "show before write" requirement); `excel_write_table(confirm=…)` honoring B14 gates.
- **Verify:** diff snapshot tests; gated write tests.

#### [ ] E3 — Recipe W5: QTO round-trip
- **Lane:** PY · **Size:** M · **Depends on:** E2, C-gate
- **Do:** `recipes/qto-roundtrip.yaml`: Revit schedules → Excel table → (human edits rates) → diff → write rates into Revit shared parameters (confirmation-gated). Mock e2e; live evidence task appended to C13 list.
- **Verify:** mock e2e in CI per blueprint §6 W5 acceptance.

#### [ ] E4 — Excel cloud variant (Microsoft Graph)
- **Lane:** PY · **Size:** L · **Depends on:** E1; **[H]** sub-step: Azure app registration (you)
- **Do:** `providers/msgraph.py` (OAuth PKCE per cloud provider pattern in `cloud.py`): workbook table read/write on SharePoint/OneDrive; same tool names with `graph_` prefix; live tests behind `AEC_LIVE_TESTS`.

#### [ ] E5 — ACC/Forma: AEC Data Model reads
- **Lane:** PY · **Size:** M · **Depends on:** A-gate; **[H]** sub-step: APS app + ACC project access (you)
- **Do:** Extend `AutodeskDataProvider`: AEC Data Model GraphQL queries (elements + properties of cloud-hosted designs), hub/project/folder navigation hardening, pagination + rate-limit handling.
- **Verify:** mocked GraphQL tests; live evidence recorded.

#### [ ] E6 — ACC: Issues publishing from W2
- **Lane:** PY · **Size:** M · **Depends on:** E5, C10
- **Do:** `acc_create_issue` (ACC Issues API) + W2 recipe option `publish_issues: acc` mapping clash rows → issues (title, location, linked element IDs); idempotency so re-runs update rather than duplicate.
- **Verify:** mocked API tests; live: clash from W2 appears as an ACC issue (evidence).

#### [ ] E7 — ACC webhooks (model-updated triggers)
- **Lane:** PY · **Size:** M · **Depends on:** E5, D6
- **Do:** Register APS webhooks (model version added) → local handler endpoint or polling fallback → optionally auto-trigger a named recipe (the "dashboards never stale" loop closed end-to-end).

#### [ ] E8 — Solibri spike → ADR 0004
- **Lane:** PY (research) + **[H]** Solibri license (you) · **Size:** M · **Depends on:** A9
- **Do:** Verify against current Solibri docs: REST API availability/port/launch flags (historically `--rest-api-server-port=10876`, `/solibri/v1/…`), Open API (Java) plugin terms, what's automatable (open model, open ruleset, run checking, export BCF/Excel). Decide track (a) REST switch, (b) Java plugin, (c) file-exchange fallback (IFC in / BCF out, no Solibri API at all). Record as `docs/0004-solibri-integration.md` with evidence.

#### [ ] E9 — Solibri switch implementation
- **Lane:** per ADR 0004 (PY if REST; NET/Java if plugin) · **Size:** L · **Depends on:** E8
- **Do:** Implement the chosen track as `providers/solibri.py` (+ plugin if required): `solibri_open_model`, `solibri_run_ruleset`, `solibri_get_results`, `solibri_export_bcf`; mock + tests; Contract v2 registry entry if it's a desktop switch.
- **Verify:** mock e2e; live run evidence with Solibri Office version recorded.

#### [ ] E10 — W3 extension: Solibri findings in the health score
- **Lane:** PY · **Size:** S · **Depends on:** E9, C11
- **Do:** Add optional Solibri step to `model-health.yaml` (capability `rule_check`, fallback: skip with degradation); merge findings into the score; BCF artifacts attached to the Run Record.

**Phase E gate:** W5 live round-trip done; a clash published as an ACC issue; Solibri findings (or a documented fallback) in the health score.

---

## PHASE F — Platform, Distribution & Docs (parallel lane from early on)

#### [ ] F1 — Switch SDK template
- **Lane:** NET · **Size:** M · **Depends on:** B5 (reference implementation)
- **Do:** Extract a `templates/switch-csharp/` template (cookiecutter-style): HttpListener loop, attribute command registry, Contract v2 (token/registry/capabilities), result envelope — so Solibri/Tekla/SketchUp switches start from a working skeleton. Include a `TEMPLATE-README` with the 10-step "new switch" checklist.
- **Verify:** template instantiates and builds as a standalone "echo" switch.

#### [ ] F2 — MkDocs documentation site
- **Lane:** DOCS · **Size:** M · **Depends on:** A5, A6
- **Do:** MkDocs Material in-repo; nav: Getting Started (zero-switch IFC demo FIRST), per-switch install guides, workflows W1–W5, generated tool catalog, Run Record schema, security model, licensing/commercial page (strategy doc Rung 1 funnel); GitHub Pages deploy workflow.
- **Verify:** site builds in CI; deployed.

#### [ ] F3 — First-run tutorial: the zero-switch demo
- **Lane:** DOCS+PY · **Size:** M · **Depends on:** C11, F2
- **Do:** A guided "10 minutes, no licenses" walkthrough: install hub → sample IFC (commit a small open-licensed fixture) → run W3 → open results; plus a `aec-bridge demo` CLI command that scaffolds the sample workspace.
- **Verify:** executed verbatim on a clean machine/VM; timing recorded.

#### [ ] F4 — Release automation per switch
- **Lane:** PY/NET · **Size:** M · **Depends on:** B5, B10
- **Do:** Extend `release.yml`: independent versioned artifacts per switch (revit-switch-<year>-vX.zip, navisworks-switch-…), SHA256SUMS, hub wheel + `.mcpb`; release notes generated from conventional commits; (stretch) winget manifest for the hub.
- **Verify:** tag → draft release with all artifacts + checksums.

#### [H] F5 — Autodesk App Store submission prep
- **Lane:** HUMAN · **Size:** L · **Depends on:** A9, B5, B10, F4
- **Do (you):** Publisher account, store packaging requirements (MSI/bundle, help docs, support URL), submission for Revit switch first, Navisworks second. Credibility badge per strategy doc.

#### [ ] F6 — Sample assets pack
- **Lane:** DATA · **Size:** S · **Depends on:** C9–C12
- **Do:** `samples/`: small open IFC, massing JSON fixture, demo recipes, one pre-baked lake with 5 Run Records (feeds D3/D4 templates and F3 tutorial).

#### [ ] F7 — README + ecosystem story refresh
- **Lane:** DOCS · **Size:** S · **Depends on:** C-gate
- **Do:** Rewrite README around the orchestration story (workflows first, tool counts second), accurate switch matrix with per-switch install links, hero GIF placeholder, link to docs site.

#### [ ] F8 — Rhino native plugin decision (blueprint OD2)
- **Lane:** DOCS→NET · **Size:** S (decision) + L (optional build) · **Depends on:** C13 (live W1 evidence shows whether proxy suffices)
- **Do:** ADR: proxy-first verdict with evidence. Only if proxy proves limiting: build `.rhp` from F1 template exposing live-document geometry/layers/usertext routes; Food4Rhino packaging.

---

## PHASE G — Wave 3 Specification Cards (spec-only; each must "earn its place" before implementation)

Each G-task produces a 1–2 page spec in `docs/specs/` answering: named workflow it enables · API surface + auth · adapter type (per blueprint §3/§8 taxonomy) · licensing position (extends A9) · test-access plan · go/no-go recommendation. **No packages, no code** (integration-expansion-handover rule: no empty connector packages).

#### [ ] G1 — Archicad provider spec + spike
- **Size:** M · Highest-priority G: Archicad's local JSON API (official Python package, default port 19723 — verify) means a **hub-side provider with no add-in**, unusually low friction. Spike: connect to a running Archicad, list elements/properties. Target workflow: W3 health audit on Archicad projects. **Implementation promoted to I5** (2026-06 ecosystem research: the community Tapir JSON command schema auto-generated 137 tools — integration is nearly free).

#### [ ] G2 — Tekla Structures adapter spec
- **Size:** S · .NET local adapter (Tekla Open API connects to the running instance); target workflow: structural QTO into W5; licensing + version-pinning notes mandatory.

#### [ ] G3 — SketchUp switch spec
- **Size:** S · Ruby extension implementing Contract v2; target: early-design massing into W1 as an alternative concept source.

#### [ ] G4 — Bentley iTwin provider spec
- **Size:** S · Cloud OAuth; target: changeset-aware W3 audits for infrastructure clients.

#### [ ] G5 — Trimble Connect provider spec
- **Size:** S · Cloud; target: BCF topic publishing from W2 (vendor-neutral alternative to ACC Issues).

#### [ ] G6 — Procore provider spec
- **Size:** S · Cloud; target: W2 clash → Procore observations/RFIs for GC-side users.

#### [ ] G7 — Primavera (P6/Cloud) provider spec
- **Size:** S · Cloud; target: 4D — join Run Record quantities to schedule activities in the lakehouse.

---

## PHASE H — Any-AI Access Layer (Chapter 2)

> Goal: the average BIM professional drives the hub from **whatever AI they already have** — Claude, ChatGPT, Copilot, Gemini, or a local model — and installs everything without being a developer. This turns the machine (A–G) into a product anyone can use. H1's ADR amends blueprint §2 Layer 0.

#### [ ] H1 — ADR 0005: access-layer architecture (the four doors)
- **Lane:** DOCS+PY · **Size:** M · **Depends on:** B14
- **Do:** Write `docs/0005-any-ai-access-layer.md` deciding: the hub exposes four doors — (1) MCP stdio (today, unchanged); (2) **remote MCP** over Streamable HTTP — the universal door, since Claude, ChatGPT connectors, Copilot Studio, Gemini CLI and most agent frameworks speak MCP-over-HTTP as of 2026; (3) **REST/OpenAPI facade** for AIs and automation tools without MCP (custom GPT Actions, Power Automate, n8n, Zapier); (4) bundled **BYO-LLM console** (H5). Decide: auth = per-client API keys mapped to B14 policy scopes; remote default exposure = workflows + read-only tools (raw mutating/high-risk tools need an explicit scope); bind defaults to loopback.
- **Done when:** ADR merged; blueprint §2 Layer-0 diagram amended; H2–H7 are implementable without further decisions.

#### [ ] H2 — Remote MCP endpoint (Streamable HTTP) + API-key auth
- **Lane:** PY · **Size:** M · **Depends on:** H1
- **Do:** Serve the existing MCP server over Streamable HTTP (configurable host/port, default `127.0.0.1:8787`; SSE fallback for legacy clients); API keys created via `aec-bridge keys` (hashed at rest), each key carrying a B14 policy scope; audit every remote call (redaction rules apply).
- **Verify:** pytest MCP-client-over-HTTP round-trip (list + call); missing/bad key → 401; key never appears in logs or audit fixtures.

#### [ ] H3 — REST facade + generated OpenAPI spec
- **Lane:** PY · **Size:** M · **Depends on:** H1, C6
- **Do:** HTTP API `/api/v1`: `GET /tools`, `POST /tools/{name}`, `GET /workflows`, `POST /workflows/{name}/run`, `GET /jobs/{id}`, `POST /runs/{id}/confirm` — generated from the same capability manifests as the tool catalog (one source of truth, per Standing Rule 5); publish `docs/openapi-howto.md` with paste-into-custom-GPT-Action and n8n/Power Automate walkthroughs.
- **Verify:** generated `openapi.json` validates; e2e REST test drives the FakeProvider 3-step recipe.

#### [ ] H4 — `aec-bridge connect`: client config generator
- **Lane:** PY · **Size:** S · **Depends on:** H2
- **Do:** CLI command printing/writing ready-to-paste configs per client: Claude Desktop/Code, VS Code `mcp.json`, Cursor, ChatGPT connector (remote URL + key), Copilot Studio, Gemini CLI, plus a generic remote-MCP block; `--all` writes them under `<workspace>/connect/`. `aec-bridge doctor` (B13) reports which doors are live.
- **Verify:** snapshot tests per client template.

#### [ ] H5 — BYO-LLM chat console (`aec-bridge ui`)
- **Lane:** PY · **Size:** L (split allowed) · **Depends on:** H3
- **Do:** Minimal local web app served by the hub: chat pane wired to ANY OpenAI-compatible endpoint (cloud key or local Ollama/LM Studio — endpoint + model picker), tool-calling against the REST facade, live job/run feed, confirmation buttons for gated steps, Run Record viewer. No heavy frontend build: static page + a light JS approach, shipped inside the wheel.
- **Done when:** a user with only Ollama on a laptop runs W3 end-to-end from the browser, fully offline.
- **Verify:** e2e test against a scripted fake OpenAI-compatible server; manual Ollama smoke recorded as evidence.

#### [ ] H6 — Recipe-authoring kit for AIs
- **Lane:** PY+DOCS · **Size:** M · **Depends on:** C1, C6
- **Do:** `workflow_validate(recipe)` tool returning precise schema errors; publish the recipe JSON Schema; `docs/authoring-recipes.md` with a copy-paste "author a recipe" prompt so any LLM can draft → validate → dry-run → save; user recipes in `<workspace>/recipes/` are listed by `workflow_list`.
- **Verify:** invalid recipe → actionable errors (tested); a saved authored recipe runs in mock mode.

#### [ ] H7 — Network exposure hardening
- **Lane:** PY · **Size:** M · **Depends on:** H2, H3
- **Do:** Non-loopback bind requires explicit opt-in env + logged warning; per-key rate limits; request size caps; key rotation/revocation; CORS rules for the console; optional TLS via user certs; extend B15 abuse tests to the remote surface; update `docs/security.md`.
- **Verify:** security suite: LAN bind refused by default; rate limit → 429; revoked key refused.

#### [ ] H8 — Non-developer install path
- **Lane:** PY/NET · **Size:** M · **Depends on:** F4, B13, H4
- **Do:** One Windows entry point (PowerShell one-liner and/or winget) that installs the hub, detects installed Revit/Navisworks versions, offers the matching switch installers, then runs `doctor` + `connect`; "10-minute" quickstart page on the F2 docs site.
- **Verify:** clean Windows VM → connected AI client in ≤10 min; timing recorded ([H] assists the VM run).

**Phase H gate:** a user with only ChatGPT (or any remote-MCP client) drives W3 through the remote door; a user with only Ollama does it offline through the console; neither needed a text editor to install.

---

## PHASE I — Popularity Pack: neutral-layer bridges (research-ranked, Chapter 2)

> Goal: ship the marginal capabilities most likely to go popular, ranked by (popularity among average BIM professionals) × (ease of integration) — 2026-06 ecosystem research. Strategic through-line: desktop Revit MCP is being commoditized (Revit 2027 ships a built-in MCP server; many community servers exist). The defensible position is the **neutral coordination layer** — IFC + BCF + Speckle + clash + identity — that no vendor will build across competitors' tools.

#### [ ] I1 — BCF provider (open gap: no MCP bridge exists anywhere)
- **Lane:** PY · **Size:** M · **Depends on:** A8
- **Do:** `providers/bcf.py` (in-hub, optional extra `[bcf]`, e.g. IfcOpenShell's bcf module): `bcf_read`, `bcf_create_topic`, `bcf_add_viewpoint`, `bcf_write` for BCF 2.1 + 3.0 files; topics carry element GUIDs through the identity mapper.
- **Verify:** round-trip tests on fixture `.bcf` files (2.1 and 3.0); A8 contract suite passes.

#### [ ] I2 — W2 → BCF publishing (the killer demo)
- **Lane:** PY · **Size:** S · **Depends on:** I1, C10
- **Do:** W2 recipe option `publish_issues: bcf` mapping clash results → BCF topics with viewpoints + components; the `.bcf` attached to the Run Record as an artifact; idempotent re-runs update topics instead of duplicating.
- **Verify:** mock e2e: clash fixtures → valid BCF parsed back by an independent reader in the test.

#### [ ] I3 — IFC→glTF + self-contained web-viewer artifact
- **Lane:** PY · **Size:** M · **Depends on:** C7
- **Do:** `ifc_to_gltf(ifc_path)` (IfcOpenShell geometry/IfcConvert, optional extra); `aec_make_viewer(gltf)` emitting ONE self-contained HTML file (embedded glTF + bundled minimal three.js viewer) attached as a Run Record artifact — the "show me the model/clash" answer that opens in any browser and travels by email.
- **Verify:** fixture IFC → `.glb` + `.html`; the HTML loads offline in a headless-browser test.

#### [ ] I4 — `aec_describe_model`: the model digest
- **Lane:** PY · **Size:** S · **Depends on:** C7
- **Do:** One tool: IFC/Revit source → semantic-graph-powered digest designed for LLM consumption (counts by category/level, spatial tree summary, units, georeferencing, top warnings), markdown + JSON forms — the "explain this model" feature, zero desktop software required.
- **Verify:** fixture IFC digest snapshot test.

#### [ ] I5 — Archicad provider via Tapir (promoted from G1)
- **Lane:** PY · **Size:** M · **Depends on:** G1
- **Do:** `providers/archicad.py` over Archicad's local JSON/Tapir API; generate the tool surface from Tapir's command schema (community precedent auto-generated 137 tools); read-first scope (elements, properties, project navigation); target workflow: W3 health audit on a live Archicad project.
- **Verify:** mocked JSON-API tests; live evidence against a running Archicad recorded.

#### [ ] I6 — Grasshopper definition runner
- **Lane:** PY · **Size:** M · **Depends on:** A4
- **Do:** `gh_run_definition(path, inputs)` via Rhino.Compute (Hops pattern): submit a `.gh` definition, bind inputs, return outputs/geometry — the computational-design on-ramp into W1 for the large GH community; document limits (no live canvas).
- **Verify:** mocked Compute tests; live smoke against Rhino.Compute recorded.

#### [ ] I7 — Drop-folder automation
- **Lane:** PY · **Size:** M · **Depends on:** C6, D6
- **Do:** `aec-bridge watch <folder> --recipe model-health`: file watcher triggering a named recipe on new/changed IFC (debounced); results to `<workspace>/runs/` + optional D6 webhook — zero-prompt automation for users who will never open a chat window.
- **Verify:** e2e test: drop a fixture IFC into a temp dir → Run Record appears.

#### [ ] I8 — ADR 0006: Revit 2027 built-in MCP coexistence
- **Lane:** DOCS+PY · **Size:** M · **Depends on:** A4
- **Do:** Position against Autodesk's built-in Revit 2027 MCP server — **wrap, don't compete**: a `McpProxyProvider` target preset for the built-in server; capability mapping so recipes prefer our add-in on 2024–2026 and can use the built-in on 2027+; document the orchestrator (recipes, Run Records, identity, policy) as the value layer above any vendor MCP.
- **Verify:** ADR merged; proxy preset covered by a config test against a mock target.

**Phase I gate:** a clash run produces a BCF file another tool opens; "show me" yields a shareable offline HTML viewer; a dropped IFC produces a health report with zero prompts; Archicad participates in W3.

---

## 5. Progress Log

Agents append one line per completed task (newest first): `YYYY-MM-DD · <task-id> · <branch/commit> · <evidence summary>`

- 2026-06-13 · B1 · task/B1 · Authored docs/0002-switch-contract-v2.md establishing registry schema and auth.
- 2026-06-13 · A11 · task/A11 · Implemented ADR 0007 and added test_perf.py asserting < 10ms dispatch overhead.
- 2026-06-13 · A7 · task/A7 · Updated .gitignore for build artifacts and venv, confirmed CONTRIBUTING.md dist policy, noted missing 3dm files.
- 2026-06-12 · A0 · — · Blueprint, strategy doc, handover rewrite authored (docs only, no code).

---

**Changelog**
- 2026-06-13 — v1.1 — Chapter 2 added: Phase H (Any-AI Access Layer, H1–H8) and Phase I (Popularity Pack: BCF, web viewer, model digest, Archicad/Tapir, Grasshopper runner, drop-folder, Revit 2027 coexistence, I1–I8); Ultimate State items 8–9; G1 implementation promoted to I5; milestone map extended; A11 performance-posture ADR card added. Rationale + dispatch kit: `docs/next-chapter.md`.
- 2026-06-12 — v1.0 — Initial backlog: 7 phases, ~70 task cards, dispatch protocols for Ralph-loop and GSD-lane delegation.
