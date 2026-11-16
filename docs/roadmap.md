# Roadmap and product design

Prepared 2026-11-16 for AEC Model Bridge 1.5.0. This page replaces the adoption roadmap of 2026-10-09 and is the one place for product direction, architecture decisions, milestones and the design system. The old priorities 0 to 4 are kept and mapped to milestones in [section 6](#6-milestones).

These are plans and findings. They are not claims about shipped behaviour unless tagged as verified.

**How to read the tags**

| Tag | Meaning |
| --- | --- |
| **[V]** | Verified on 2026-11-16 by reading the code at commit `d7a18f6`, by running it here, or from the GitHub Actions API. The evidence is linked or quoted beside the claim. |
| **[I]** | Inferred from verified facts. Reasonable, not observed. |
| **[U]** | Unverified. Usually a web source that could only be seen as a search snippet, or behaviour that needs a live Revit. |

**Evidence limits of this revision**

- No Windows, no Revit and no .NET SDK were available. **Nothing in this document is new live-Revit evidence.**
- Live evidence that exists in the repository, all on Revit 2024 [V: the documents exist; their content was not re-observed]:
  - 13 October 2026: exploratory sessions on an older add-in build, in which an agent created walls, floors, roofs and families through IronPython scripts and add-in commands ([findings](bim-agent-findings.md), [behaviour notes](revit-mcp-behaviour-and-improvements.md)). These are observed writes, but they are a list of what went wrong, not an acceptance run. They predate the reworked transaction handling, read mode and approval hardening.
  - 14 October 2026: bounded read-only smoke checks on add-in 1.4.0 ([report](revit-addin-live-validation-2026-10-14.md)). No transaction was opened.
- Not observed live, on any Revit year: the plan, approve, execute flow; the native parameter writers on the current build; rollback and revert; version 1.5.0. [demo-runbook.md](demo-runbook.md) says the same: "Writes are untested in a real Revit" on the current build and "Nobody has run this demo end to end against live Revit yet" [V].
- `help.autodesk.com` and `modelcontextprotocol.io` could not be opened. Statements about Autodesk products, Revit 2027 and the MCP specification beyond what the installed SDK negotiates are [U].
- The local checkout (`d7a18f6`) is three commits behind `origin/main` (`5a2ae2f`). The difference is five documentation and changelog files, no code [V: `git diff --stat HEAD origin/main`].
- No pilot with BIM coordinators has been run.

## Summary

- **Decision.** Extend the current architecture. Do not replace a module yet. Harden identity (which document, which element), result truth (was the value really written, can it be put back) and the review pane, then prove one workflow live.
- **Flagship workflow.** Find missing or wrong parameters, preview the exact changes, a person approves, guarded writers apply, a fresh read verifies. Missing door Marks is still the first case.
- **Next three tickets.** (1) Bind plans to the document and enforce it where the write happens. (2) 64-bit element ids and UniqueId beside every id. (3) Result truth: read back after apply, record empty before-values so they can be reverted, flag duplicate drafts.
- **Biggest finding of this revision.** The documented revert route does not cover the flagship case. A plan that fills an empty Mark records the before value as `null`, and `plan_revert` refuses any element without a recorded before value [V, section 4].

## 1. Decision

### Three paths

| | A. Extend the current architecture | B. Replace one module | C. Bigger change |
| --- | --- | --- | --- |
| What | Keep Python MCP server, C# add-in, loopback HTTP, file plan store and WebView2 pane. Add document binding, 64-bit ids, write preflight, read-back, pane states. | Move the approval check into the add-in (C# verifies plan hash, approval and document inside the Revit transaction), or swap loopback HTTP for named pipes ([ADR 0014](0014-multi-revit-routing.md) option D), or drop the IronPython write path for native C# writers only. | Rebuild on Autodesk's Revit Public MCP Server and become an approval and QA layer on top of it, or rewrite the server in .NET inside the add-in. |
| Evidence for | The gate already refuses every bypass tried in the mock run of section 4 [V]. 3,135 Python tests pass locally and CI is green on all four add-in targets [V, section 5]. An open pull request already implements most of the binding ([#139](https://github.com/Sam-AEC/aec-model-bridge/pull/139)) [V: PR exists and its CI run passed; its content is not merged or reviewed here]. | The add-in does not check approval itself: no `plan_id` or approval check exists in `BridgeServer.cs` or `ExternalEventHandler.cs` [V: grep]. Any process running as the same Windows user can read the session token and call the add-in directly ([security.md](security.md), "What the token is, and is not") [V: documented limit]. | Autodesk's server is vendor-supported and reported as Revit 2027.2 only, technical preview [U]. A single .NET runtime would remove the bundled Python and IronPython. |
| Cost | M0 and M1: 19 to 30 working days plus live Revit time (section 6). | 15 to 30 days for the add-in gate alone, across three target frameworks, and every step needs a live Revit to test [I]. Gate logic would then exist in two languages. | Months. Throws away 3,135 tests and the 2024 to 2026 coverage that is the product's market window [I]. |
| Risk | The same-user bypass stays. The approval flow and the current parameter writers are unproven in live Revit, so some of the hardening may need rework after the first live run. | High regression risk in the one part that works and is well tested. No live evidence exists to tell us the current gate placement fails in practice. | Depends on a preview product we could not read about first-hand. Loses mixed-version firms. |
| Reversible | Yes. Every M0 change is additive and fail-closed; each is one pull request that can be reverted. | Partly. A transport or gate swap changes the wire contract. | No. |

### Choice: A

Extend. The safety design is sound for one model and one user, and the failures we can demonstrate today are about identity and result truth, not about where the gate sits. Take one narrow piece of B now because it is cheap and additive: mutating commands carry the expected document id and the add-in refuses a mismatch on the UI thread (ticket 1). That gives enforcement at the only place where the active document is known for certain, without moving the gate.

**Reversible first milestone.** M0 (section 6). Plans written before M0 stay valid: PR #139 hashes the binding only when it is present [U: from the PR description, to be confirmed in review]. Expiry can be switched off with `MCP_REVIT_APPROVAL_TTL=0` [U: same]. The add-in check is skipped when the payload carries no expected document, so an old server with a new add-in keeps working. A new server with an old add-in refuses bound writes (ticket 1c), so a plan is never called bound when nothing enforces it.

**Assumptions that would flip the decision**

| If this turns out true | Then |
| --- | --- |
| Live runs on Revit 2025, 2026 or 2027 show the IronPython path or `HttpListener` is unreliable (for example after Autodesk moves 2025 and 2026 to .NET 10, or under 2027 add-in isolation [U]) | Path B: native C# writers only, or named pipes. |
| A security review for an enterprise customer rejects the same-user bypass | Path B: approval verified inside the add-in. |
| Autodesk's server becomes generally available for the Revit years our users run, with a documented approve and undo model [U] | Path C: become a layer on top of it. |
| A pilot shows coordinators work only in the pane and never through an MCP client | Shrink the tool surface to the core profile and invest in the pane, not in more tools. |
| Counsel says a closed white-label build is not possible under the current licence and contributor terms | M3 becomes a GPL-only rebrand, or is dropped. |

### Three disagreements between the specialist briefs, resolved

1. **Icon colours: `design/tokens.md` or `RIBBON_ICONS.md`.** `tokens.md` is the source of truth for colour. `RIBBON_ICONS.md` becomes a how-to for regenerating and deploying icons and stops defining colours. Evidence: the "cut slate" blue `#0696D7` and orange `#FF6C00` reach only 2.90:1 and 2.49:1 on a light ribbon [V: computed, ribbon colour `#F0F0F0` assumed], so they cannot carry meaning. But the shipped PNGs are the cut-slate set, they are newer (22 October) than the token file (19 October), and `IconGenerator.LoadEmbedded` prefers them over the vector fallback [V: git log, `UI/IconGenerator.cs:100`]. So today the code and the token file disagree. The shipped icons stay until a regenerated set has been checked in a live Revit in both themes (M2). No visual change ships unseen.
2. **Document binding first, or the parameter-fix workflow first.** They are one critical path. Binding is ticket 1 because the code exists in PR #139 and because the workflow's own acceptance checks (stale document, changed value) cannot pass without it. The workflow is M1.
3. **Admin policy first, or white-label first.** Admin policy first. A BIM team needs locked approval settings whatever the brand is. Both need the same first step: product identity (name, ids, paths, ports) read from one generated source in place of constants spread over the add-in. That step is the start of M3.

## 2. Users, workflows and product boundary

### Primary users

| User | Job | What they need from the Bridge |
| --- | --- | --- |
| **BIM coordinator** (first audience, unchanged) | Find missing or wrong model data before an issue date and fix it without breaking anything else. | Exact preview, one approval, proof of what changed, a way back. |
| **BIM manager or IT** | Roll the tool out to a team on mixed Revit years and keep it safe. | Signed installer, settings a user cannot loosen, a health check, clean upgrade and rollback. |
| **Automation author** (later) | Encode office rules as rule packs and recipes. | Stable tool schemas, a module contract, a mock mode that behaves like the real thing. |

### Three flagship workflows

| # | Workflow | Manual today | Why the Bridge | Old priority |
| --- | --- | --- | --- | --- |
| 1 | **Parameter fix with approval.** Find, preview exact changes, approve, apply, verify by a fresh read. First case: 12 doors without a Mark. | Schedules and filters, multi-select, type into Properties, or an Excel round trip. | Finds the problem and fixes it in one place, with a reviewable plan. Spreadsheet tools have no finding step; generated-code tools are hard to audit [I: specialist product brief of 2026-11-16, built on search snippets; competitor detail is U]. | 0, 1, 2 |
| 2 | **Hand-over QA and change report.** One file: document identity, rule pack, findings, approved changes with before and after, what is not verified. | Screenshots and a spreadsheet. | Ties checks to approved fixes. Opens without an AI account. Implemented in open [PR #138](https://github.com/Sam-AEC/aec-model-bridge/pull/138), not merged, not run live [V: PR text]. | 4 |
| 3 | **Install to first read, on any supported Revit year.** One installer, a setup check that names the failing step and the fix. | Several components and source edits. | Mixed-version firms cannot use a 2027-only server [U]. The setup check card and `/diagnostics` endpoint exist ([first-check.md](first-check.md)) [V: documented; not seen live]. | 3 |

### Product boundary

In: reading the open Revit model, QA rules on a saved snapshot, exact parameter changes behind a human approval, proof records, a report.

Out, on purpose: authoring geometry or families as a promise, running model-written code as a headline feature, clash detection, cloud collaboration, anything that suggests Autodesk supports the product.

### Simplify, retire, defer

| Action | Item | Reason and evidence |
| --- | --- | --- |
| Simplify | Tool catalogue: make the `core` profile (51 tools) the documented starting point once [PR #140](https://github.com/Sam-AEC/aec-model-bridge/pull/140) is merged and tried in two clients | 302 tools are listed today [V: stdio `list_tools` returned 302]; the full catalogue is about 80,000 tokens ([token budget](mcp-token-budget.md)) [V: documented measurement, not re-measured]. |
| Simplify | One batch-write route for the flagship workflow | Four tools can set parameters (`revit_set_parameter_value`, `revit_set_parameters`, `revit_batch_set_parameters`, `parameter_manager_plan_set_params`). M1 uses one: a plan of single native `revit_set_parameter_value` actions, because those writers are compiled and logic-tested in CI for all four years. `revit_set_parameters` (one TransactionGroup, dry run, read-back) is the better design but its header says nothing has run against a live Revit [V]. Revisit at M2. |
| Simplify | One icon system (section 10) | See decision above. |
| Retire | The colour rules in `RIBBON_ICONS.md`; the retired Span mark sections in `design/tokens.md` | Superseded. |
| Retire | `ProductInfo.McpToolCount = 100` | Stale constant; the server lists 302 [V: `src/ProductInfo.cs`]. |
| Retire | The maintainer credit in the footer of every operational dialog | Noise in an error dialog [I: design brief; not re-read here]. Keep it in About. |
| Defer | Navisworks, Power BI, Rhino and Grasshopper, Speckle, sheet and drawing production, family and MEP creation, the Cerberus feature | No pilot shows that one of them blocks a coordinator. Unchanged from the old roadmap. |
| Defer | MCP elicitation and tasks, named pipes, one TransactionGroup per plan | Useful, not on the critical path. Elicitation must never become the approval step: it travels through the client the model drives ([ADR 0008](0008-approval-gate-lifecycle.md)). |

## 3. Architecture

### Components and boundaries

```
AI client ──stdio, MCP──> MCP server (Python) ──HTTP on 127.0.0.1, bearer token──> Revit add-in (C#)
                               │  plans/ proofs/ snapshots/ qaqc_issues.db              │ CommandQueue
                               │  (workspace folder)                                    │ ExternalEvent
Person ── pane (WebView2 in a DockablePane) ── panel hub (Python, port 8787) ───────────┤ UI thread, one command at a time
Person ── aec-model-bridge-approve (terminal) ── same plan store                        └ BridgeTransaction
```

| Boundary | Contract | Evidence |
| --- | --- | --- |
| Client to server | MCP over stdio. Protocol `2025-11-25` negotiated by `mcp` 1.30.0. 302 tools. Tool annotations set; no `outputSchema`; a successful result is prose plus JSON text, structured content only on errors. | [V: stdio session in section 4; `mcp_server.py`] |
| Server to add-in | `POST /execute`, `GET /result/{id}` on a loopback port picked by Windows. Bearer session token. Registry file per Revit process under `%LOCALAPPDATA%\AECModelBridge\registry`. Up to 10 concurrent HTTP requests. | [V: `Bridge/BridgeServer.cs` lines 24, 78, 84, 173, 349] |
| Inside the add-in | One command per `ExternalEvent` turn on Revit's UI thread. Native commands in `BridgeCommandFactory`, or IronPython through `PythonScriptRunner`. Writes go through `BridgeTransaction`: warnings are deleted but reported, errors roll the transaction back, a pending dialog becomes `revit_dialog_blocked`. | [V: `Bridge/BridgeTransaction.cs` lines 40, 61, 123, 128] |
| Pane to hub | WebView2 page to the add-in's `HubClient` to the Python panel hub on port 8787 (token file in `%LOCALAPPDATA%\AECModelBridge`). Only this route and the terminal tool can approve, reject or roll back. | [V: `UI/HubClient.cs:131`, `Bridge/PanelHubLauncher.cs:42`; refusal observed in section 4] |

### Model context

- Every native command acts on `ActiveUIDocument.Document` (105 uses in `BridgeCommandFactory.cs`) [V]. The add-in never compares the document with the one a plan was drafted for [V].
- `revit_get_context` returns the document `CreationGUID`, path and central path [V: `Bridge/ContextCommands.cs:38`]. The GUID alone may not tell two copies of one file apart [U]; ticket 1 binds path and title as well.
- Ids are parsed as 32-bit and then widened to `long`: `element_id` with `GetInt32()` at 15 places, other ids (view, sheet, group, type, schedule, family) at 19 more, plus id arrays [V: grep on `BridgeCommandFactory.cs`, for example lines 1381, 1419, 1459, 1580, 2758]. The code elsewhere uses the 64-bit `ElementId.Value`. An id above 2,147,483,647 cannot be addressed [I for how often real models reach that].
- Snapshots carry both `element_id` and `uid` (Revit UniqueId). QA findings carry only the uid; write tools take only the integer id [V: runbook and run in section 4].
- No ownership check before a write (`WorksharingUtils.GetCheckoutStatus` is not called anywhere) and no guard against ids that belong to a linked model [V: grep, absence]. The risk on workshared models is [I].

### State

| State | Where | Lifetime |
| --- | --- | --- |
| Plans, claims, locks | `<workspace>/plans/` | Until rejected or executed; never deleted by expiry (PR #139 hides stale drafts) |
| Proof records | `<workspace>/proofs/` | Permanent |
| Snapshots | `<workspace>/snapshots/{id}.json` | Until removed by the user |
| QA issues | `<workspace>/qaqc_issues.db` (SQLite) | Permanent; deduplicated per document, rule and element [V: section 4] |
| Command queue and results | Add-in memory | Result kept 900 s, queued work abandoned after 120 s without a poll, HTTP wait capped at 55 s [V: `CommandQueue.cs:67,69`, `BridgeServer.cs:30`] |
| Registry and tokens | `%LOCALAPPDATA%\AECModelBridge` | Per Revit session |
| Audit log | Path from `MCP_REVIT_AUDIT_LOG`; add-in log `Logs\bridge.jsonl` | Permanent ([logging-and-audit.md](logging-and-audit.md)) |

### Configuration

Today: environment variables with the `MCP_REVIT_` prefix read by the server [V: `config.py:97`], `C:\ProgramData\AECModelBridge\config\default.json` written by the installer, and settings in the pane. There is no schema version and no layer an administrator can lock [I]. The target layering is in [section 11](#11-white-label-design).

### Extension points

Modules (`module.json` plus handlers, [ADR 0009](0009-plugin-module-system.md)), rule packs (YAML, [rule-packs.md](rule-packs.md)), recipes, providers ([ADR 0001](0001-multi-provider-architecture.md)) and tool profiles. Rule: an extension can add read tools freely; any tool that changes a model must be marked mutating so the gate sees it, and can never reach the human-only tools.

### Revit version constraints

| Revit | Target framework | Script engine | Evidence |
| --- | --- | --- | --- |
| 2024 | `net48` | IronPython 2.7.12 | [V: `RevitBridge.csproj` lines 4, 56] |
| 2025, 2026 | `net8.0-windows` | IronPython 3.4.1 | [V: lines 5, 57] |
| 2027 | `net10.0-windows` | IronPython 3.4.1 | [V: lines 6, 57] |

Open questions that need Autodesk's own pages [U]: whether 2025 and 2026 will move to .NET 10 through an update (then the `net8.0` build needs a verified run or a second target), where the all-users add-in folder is in 2027, and what add-in isolation in 2027 does to IronPython and to a shared WebView2 user-data folder. Scripts must run on both IronPython 2.7 and 3.4; CI has a runtime test for that (`scripts/test-ironpython-runtime.ps1`) [V: script exists; result not seen].

### Tool schema compatibility rules

1. Tool names are frozen and brand-neutral (`revit_*`, `plan_*`, module prefixes). A rename is a new tool plus a deprecation under [deprecation-policy.md](deprecation-policy.md).
2. Only add optional arguments. A new required argument means a new tool name.
3. Ids stay JSON integers. After ticket 2, every tool that takes `element_id` also accepts `element_uid`, and every result returns both.
4. Plan content is versioned by `hash_version`. A new hashed field is hashed only when present, so stored plans keep their hash.
5. `outputSchema` is added per tool with a contract test, starting with about 20 read and plan tools (M2). The text result stays as a short summary. Reason: the SDK validates output against the schema, so a mismatch turns a good result into an error [U: SDK behaviour not tested here].
6. The human-only tools (`approve_plan`, `reject_plan`, `rollback_plan`) are never listed to a client. This is tested and was observed [V: section 4].

## 4. One end-to-end flow: an approved batch edit on the synthetic model

The model is the [canonical fixture](../fixtures/canonical-model/README.md): 60 doors, the last 12 without a Mark, and 25 rooms, the last 3 without a Number [V: `manifest.json`, `seeded-defects.json`]. The live variant below adds two doors owned by a second user, to exercise skips. The same numbers are used in the [design prototype](design/prototype.html).

### Intended behaviour, step by step

| Step | What happens | Status |
| --- | --- | --- |
| 1. Read | Capture a snapshot of the open document. Record document id, title, time. | Snapshot tool exists [V]. Document id check against the open document: PR #139 [U until merged]. |
| 2. Find | `qaqc_checker_run_check` with the `core` pack reports `door_missing_mark` 12 and `room_missing_number` 3. | Counts reproduced in mock on a synthetic snapshot [V]. Not seen live. |
| 3. Intended changes | Ten doors get Marks `D-049` to `D-058`, continuing the existing `D-001` to `D-048`. The coordinator chooses the pattern; the assistant does not guess it. Ids are looked up from the snapshot, never typed. | Plan drafted in mock [V]. The server does not check that proposed values are unique [V: runbook]; ticket 3 adds a warning. |
| 4. Skips | Two doors (`300058`, `300059`) are owned by another user. They are listed with a reason and are not in the plan. 48 doors that have a Mark are never touched. | `skipped` is stored in the plan, shown by the terminal tool and copied to the proof [V]. Detecting ownership needs the write preflight (M1) [U]. |
| 5. Units | Mark is text, so no conversion. Rule for numeric parameters: payloads are SI with an explicit unit; the preview shows the value in project units and in SI. | The add-in converts with `UnitTypeId` in 74 places [V: grep]. The numeric path of `revit_set_parameter_value` is not audited [U]. |
| 6. Preview | The pane shows 10 changes (element, level, value now, value after), 2 skipped, plan id, plan hash, bound document. Approve is disabled until the review was opened. | Review gating exists in the pane [V: `panel/app.js:452`, `data-review-blocked`]. Layout in the prototype is a proposal. |
| 7. Approve | A person approves in the pane or with `aec-model-bridge-approve`. The approval is bound to the plan hash. | Observed in mock: approval over MCP refused; edited plan refused [V]. |
| 8. Stale plan | Before approval and before each change, the plan's document and recorded before-values are compared with the model. A mismatch refuses, consumes nothing and asks for a new preview. | Document: PR #139 [U]. Before-value drift at execution: **not implemented** [V: [ADR 0017](0017-approval-document-binding-and-expiry.md), "tracked separately"]. Ticket 3. |
| 9. Apply | `execute_plan` runs each action once, in its own Revit transaction. | Mock [V]. Live [U]. |
| 10. Cancellation | Cancel stops actions that have not started. The action Revit is writing finishes. A cancelled job keeps its approved action consumed. The pane says "cancel requested" until the add-in confirms, then shows how many doors were written. | Job cancel sets the status to `cancelled` at once while Revit may still be running the action [V: `jobs.py` lines 343, 344]. Two-phase status and the live cancel check are in M1. |
| 11. Partial failure | A failed action is recorded and never reopened. The plan stays `approved`, not `executed`. A retry is a new plan with a new approval. | [V: `approval_provider.py`, `_execute_plan` docstring and code]. |
| 12. Rollback limits | Three routes, in order: Revit Undo (one entry per door, this session only); a revert plan (`plan_revert`, needs approval); restore the file. After ticket 3 a revert plan covers exactly the actions that were executed, also for a partly applied or cancelled plan. | Today `plan_revert` refuses any plan whose outcome is not `success` and any element without a recorded before value [V: `approval_provider.py` lines 352, 365; `proof.py:412`]. **So a half-cancelled or partly failed batch cannot be reverted at all, and neither can values that were empty.** |
| 13. Final audit | Proof record: plan hash, approver account, document, each element with before and new value, skipped, outcome. A fresh snapshot and QA run: `door_missing_mark` 12 to 2, `room_missing_number` 3 to 3. | Proof record produced in mock [V]. It states that values were not re-read [V]. Fresh-read verification is ticket 3 and M1. |

### What was run (mock mode, twice)

Environment: Linux, Python 3.13.18, `mcp` 1.30.0, package installed editable from `packages/mcp-server-revit`, commit `d7a18f6`. No Revit.

The driver was a throwaway script in the session scratchpad (not in the repository; ticket 3 adds a kept version under `scripts/demo/`). It builds a snapshot with the fixture's counts and fixed ids (`snapshot_id` `CANONICAL-SYNTH-0001`, doors `300000` to `300059`), writes it to `<workspace>/snapshots/`, starts the real server over stdio and calls the real tools. Each run used a new empty workspace.

```bash
cd packages/mcp-server-revit
MCP_REVIT_MODE=mock python <scratchpad>/flow/run_flow.py A
MCP_REVIT_MODE=mock python <scratchpad>/flow/run_flow.py B

# inside the driver, per run:
#   server:  python -m revit_mcp_server.mcp_server
#            env MCP_REVIT_MODE=mock MCP_REVIT_WORKSPACE_DIR=<ws> MCP_REVIT_ALLOWED_DIRECTORIES=<ws>
#   person:  python -m revit_mcp_server.approve_cli --workspace <ws> show|reject|approve <plan_id> --yes
```

The approval was given by the script with `--yes`, standing in for a person, in a scratch workspace only.

Tool calls and results, identical in both runs (`ok` or `ERROR` is the MCP `isError` flag):

| # | Call | Result |
| --- | --- | --- |
| 1 | `qaqc_checker_run_check` (core) | ok: 13 rules, 15 findings: `door_missing_mark` 12, `room_missing_number` 3 |
| 2 | same call again | ok: still 15 open issues, same issue ids (no duplicates) |
| 3 | `parameter_manager_filter_params` (doors, Mark) | ok: 60 rows with `uid` and `element_id` |
| 4 | `revit_set_parameter_value` with no plan | ERROR `approval_blocked`: "Mutating tool 'revit_set_parameter_value' requires a valid 'plan_id' parameter." |
| 5 | `plan_actions`: 10 actions, 2 skipped, review block | ok: state `pending`, `hash_version` 2, no `binding` key |
| 6 | the same `plan_actions` again | ok: **a second pending plan**, different id and hash |
| 7 | `execute_plan` before approval | ERROR: "is in state 'pending', not 'approved'. Execution blocked." |
| 8 | `approve_plan` over MCP | ERROR: "'approve_plan' is not available to AI clients." Not in the tool list either. |
| 9 | terminal: reject the duplicate; `execute_plan` on it | ERROR: "is in state 'rejected'" |
| 10 | terminal: approve; `execute_plan` | ok: state `executed`, 10 results, each `"mock": true` |
| 11 | `execute_plan` again; single action again with the plan id | ERROR both: "is in state 'executed', not 'approved'" |
| 12 | `get_proof_bundle` | ok: outcome `success`, 10 elements, 2 skipped, `verification`: "UNVERIFIED against the live model: outcome is what the provider reported; values were not re-read after writing." |
| 13 | `qaqc_checker_run_check` on the same snapshot | ok: still 12 and 3 (mock mode has no model to re-read) |
| 14 | approve a one-action plan, edit its stored value on disk, `execute_plan` | ERROR: "changed after it was approved (or has no approval record). Execution blocked" |
| 15 | `plan_revert` on the executed plan | ERROR: "Cannot revert plan …: no before value was recorded for: 300048/Mark, … 300057/Mark." |

Stability across the two runs:

| Item | Run A | Run B | Stable |
| --- | --- | --- | --- |
| Snapshot SHA-256 (first 16) | `f887600730136223` | `f887600730136223` | yes |
| Findings by rule | 12 doors, 3 rooms | 12 doors, 3 rooms | yes |
| Target element ids | `300048` to `300059` | `300048` to `300059` | yes |
| QA issue ids after a re-check in the same workspace | 15, identical | 15, identical | yes, within a workspace |
| First door issue id | `15b85cc2-…` | `04561b89-…` | no: random per workspace |
| Plan id | `plan_b366ce3444a0` | `plan_4977f5fe0e77` | no: random by design |
| Plan hash | `sha256:a3ef52fd…` | `sha256:8b58d85c…` | no: the hash covers plan id, action ids and creation time [V: `proof.py:324`] |
| Fingerprint of tools, arguments, snapshot and skips (computed by the driver, not by the product) | `03df023baa17e0bb` | `03df023baa17e0bb` | yes |
| Pending plans after two identical drafts | 2 | 2 | duplicate not prevented |
| Proof outcome, changes, skipped | success, 10, 2 | success, 10, 2 | yes |

### Findings from the run

1. **The gate holds.** Six bypass attempts were refused with clear messages (rows 4, 7, 8, 9, 11, 14) [V].
2. **Duplicate drafts are not prevented.** The same intent drafted twice gives two pending plans. Each can only run once, and a second run of the same change on a model is harmless for a text value, but the approver sees two cards for one job [V]. QA issues are deduplicated [V].
3. **Empty before-values cannot be reverted.** The proof marks `before_recorded` false whenever the before value is `None` (`proof.py:412`), and `plan_revert` refuses those elements (`approval_provider.py:365`) [V]. In mock mode the read returns no value. In a live Revit the add-in returns `null` when `Parameter.HasValue` is false (`BridgeCommandFactory.cs:1721`) [V: code], which is the expected state of a Mark that was never set [I: needs a live check]. [proof-and-revert.md](proof-and-revert.md) says so in one line ("an empty value counts as not recorded") [V]. For the flagship workflow that leaves Revit Undo as the only way back.
4. **The proof does not confirm the write.** It says so itself (row 12) [V]. "Preview matches applied" cannot be measured yet.
5. **Mock mode proves mechanics, not model changes.** The after-check still shows 12 doors (row 13). Nothing here is evidence about Revit.

## 5. Compatibility matrix

Four separate questions. A tick in one column says nothing about the next.

| Revit | Documented support | CI build | Mock and integration tests | Observed in live Revit |
| --- | --- | --- | --- | --- |
| 2024 | Listed as available ([compatibility.md](compatibility.md)) [V] | Passed: job `addin (2024)`, `net48` [V] | Passed (not year-specific) [V] | **Partial, and not on this version.** Read-only smoke checks on 14 October 2026, add-in 1.4.0, Revit build 24.3.10.22 ([report](revit-addin-live-validation-2026-10-14.md)). Exploratory script-driven model creation on 13 October on an older build ([findings](bim-agent-findings.md)). Not observed: approval flow, native parameter writers on the current build, rollback, revert. Version 1.5.0 has not been run live. |
| 2025 | Listed as available [V] | Passed: job `addin (2025)`, `net8.0-windows` [V] | Passed (not year-specific) [V] | **None** |
| 2026 | Listed as available [V] | Passed: job `addin (2026)`, `net8.0-windows` [V] | Passed (not year-specific) [V] | **None** |
| 2027 | Listed as available [V] | Passed: job `addin (2027)`, `net10.0-windows` [V] | Passed (not year-specific) [V] | **None** |

What each column rests on:

- **Documented support.** `compatibility.md` says "Revit 2024 to 2027: Available". That wording is stronger than the evidence in the last column. M2 changes it to state the live status per year.
- **CI build.** Workflow [`ci.yml`](../.github/workflows/ci.yml), job `addin`, matrix 2024 to 2027: build with `scripts/build-addin.ps1`, then `dotnet test packages/revit-bridge-addin-tests` (queue, read mode, paths, failure text; no Revit, no Autodesk assemblies) [V: workflow file]. Latest run on `main`: [run 43840527454](https://github.com/Sam-AEC/aec-model-bridge/actions/runs/43840527454), commit `5a2ae2f`, 2026-11-16, conclusion success; jobs `addin (2024)`, `addin (2025)`, `addin (2026)`, `addin (2027)`, four `python` jobs, `rhino-addin`, `sbom`, `workflow-lint` and `ci-success` all success [V: GitHub REST API through `gh api repos/Sam-AEC/aec-model-bridge/actions/runs/43840527454/jobs`. The GitHub MCP actions tool named in the brief was not available in this session, so the same data was read through the REST API]. That commit is three documentation commits ahead of the local checkout. A green build means the add-in compiles against reference assemblies and its Revit-free logic tests pass. It does not load the add-in in Revit.
- **Mock and integration tests.** The Python suite does not vary by Revit year. Local run at `d7a18f6` on Linux, Python 3.13: **3,135 passed, 148 skipped, 2 deselected** in 174 s [V: `python -m pytest tests -q --deselect tests/test_wheel_contents.py`]. Deselected: the wheel-build test, which needs network access. Skipped: 134 panel browser tests (no usable Chromium for that suite here), 9 compiled transaction-policy tests (no .NET SDK), 2 live e2e tests, 3 others. CI ran the suite on Windows with Python 3.11, 3.12, 3.13 and on Ubuntu 3.12 in the run above, all success [V]. The stdio flow in section 4 is a further integration check [V].
- **Observed live.** Only what a person saw in a running Revit and wrote down.

MCP clients: Claude Desktop, VS Code with Copilot, Cursor and Codex are documented; none has a recorded end-to-end run of the approval flow [V: `compatibility.md`, [demo-runbook.md](demo-runbook.md)].

## 6. Milestones

Effort is in working days for one maintainer with AI assistance. Ranges assume review time is included and exclude waiting for a Revit licence, a certificate or counsel.

### M0. Baseline fixes: trust the identity and the result

| | |
| --- | --- |
| Outcome | A plan cannot run in another document. Ids do not truncate. The proof says whether each value was read back. A filled-in empty value and a half-applied batch can be reverted. The approver is told about a duplicate draft. An upgrade can be undone. |
| Effort | 8 to 13 days. Assumes PR #139 needs only the changes in ticket 1, and one Windows machine with any supported Revit for about three days. |
| Components | `security/approval.py`, `security/binding.py` (PR #139), `security/proof.py`, `providers/approval_provider.py`, `Bridge/BridgeCommandFactory.cs`, `Bridge/ExternalEventHandler.cs`, `revit-bridge-addin-tests`, `approve_cli.py`. Installer: keep the previous `bin\<year>` folder as a backup and document the restore. |
| Acceptance checks | The three tickets in section 7. Upgrade and downgrade: M0 changes the wire contract between server and add-in (`protocol_version` 3, new payload fields), and today the installer deletes the previous `bin\<year>` folder before copying [V: `AECModelBridge.iss` lines 75 to 80], so there is nothing to go back to. The installer moves the previous folder to `backup\<year>-<version>` (keep the last two) as `deploy-addin.ps1` already does for developers [V: script header], and a documented command restores it. Checked with `scripts/test-installer.ps1` on a throw-away machine: install the previous release, upgrade, restore, and the restored add-in loads. |
| Proof required | CI green on all four add-in jobs and all Python jobs. The new tests listed in the tickets, first committed as strict expected failures, now pass. **Two-copies live test** on one Revit year, on a scratch project: make a Save As copy of the fixture and open both. Record whether the two `CreationGUID` values are equal. Draft and approve a plan in copy A, make copy B active, execute: see the refusal, confirm B is unchanged and the plan is still approved. Repeat with a detached copy if the model is workshared. **Skew test:** new server against the previously installed add-in refuses bound writes; restoring the previous add-in from the backup loads and reads. |
| Rollback | Code: revert the pull request; binding and the add-in check are additive, and `MCP_REVIT_APPROVAL_TTL=0` turns expiry off. Installed machines: restore the previous add-in folder from the backup. A new server then refuses bound writes against it and says why, instead of writing unprotected. |

Covers the open half of old priority 0 (snapshot belongs to the open document).

### M1. Shippable vertical slice: missing door Marks, live, in one Revit year

| | |
| --- | --- |
| Outcome | A coordinator completes find, preview, approve, apply and verify on the canonical fixture in a real Revit, twice, with the same counts, and can put the values back. Old priorities 0, 1 and 2. |
| Effort | 11 to 17 days, plus live sessions. Assumes Revit 2024 or 2026 is available on a test machine; 2024 is the only year with any prior live evidence. |
| Components | Write preflight in the add-in (ownership through `WorksharingUtils`, element is in the active document and not in a link, parameter not read-only, no open transaction). Pane states: partial failure, stale plan, document switched, duplicate draft, already applied, cancel requested. Two-phase cancel status (`cancel_requested`, then `cancelled` once the add-in confirms), moved here from M2 because a cancelled batch is a normal coordinator action, not an edge case. Shared transaction failure handling for the parameter writers. The pane's health check passes a `snapshot_id` (it sends none today [V: runbook]). Merge PR #138 (report). A kept mock driver and the updated [demo-runbook.md](demo-runbook.md). |
| Acceptance checks | Fixture rebuilt; rule counts 12 and 3 on two runs. After the fix: 0 and 3. Only the 12 selected doors change; the 48 populated Marks are byte-identical before and after. A rejected plan leaves all parameters unchanged. On the workshared variant: the 2 doors owned by a second user are skipped with a reason, 10 change, the after count is 2. A forced failure (dialog open in Revit) gives a partial result that is not shown as done. A document switch and a changed value both refuse. A revert plan restores 12 empty Marks. **Cancel mid-apply, live:** the pane shows "cancel requested" until the add-in confirms; the number of doors the proof reports as written equals the number changed in the model; no door changes after the confirmation; a revert plan for the written subset puts exactly those doors back. |
| Proof required | A dated record like the 14 October report: Revit build, add-in version, commit, counts before and after, parameter dump diff, proof records, screenshots or a recording. Published only after the run. |
| Rollback | The slice adds preflight refusals and pane states. Each is one pull request. If the live run shows the native writer is unsafe, stop and ship M0 only; the read-only product stays as it is. |

Carried over from the deleted session hand-over note (`bridge-upgrade-handoff.md`), so its open next steps are not lost:

1. **Shared transaction failure handling.** Finish `CommitChecked`, structured Revit failure messages and `on_error` across the writers, plus creator argument defaults and plan-view creation. The parameter writers are in M1; the rest follows in M2.
2. **Validate the recovered QA and documentation tools against live Revit** (openings, roofs, family probe, MEP report, naming and parameter checks, `revit_review`). M2, one record per Revit year.
3. **Mutating acceptance only on an owner-opened scratch project**, never on a production copy. This is a rule for every live run in M0 and M1.

Also still open from the 14 October report: reconnect a stale chat MCP process after a Revit restart (LIVE-02), and return a refusal as a refusal and not HTTP 500 (LIVE-03).

### M2. First public-quality release

| | |
| --- | --- |
| Outcome | Every advertised Revit year has a recorded live smoke run of the M1 flow. The installer is signed. A new user reaches a first read without editing source. Old priorities 3 and 4. |
| Effort | 15 to 25 days. Assumes access to Revit 2024, 2025, 2026 and 2027 (four installs or four VMs), a code-signing certificate, and that the .NET 10 question for 2025 and 2026 is answered from Autodesk's own page. |
| Components | Authenticode signing of the installer and DLLs in `release.yml` (today unsigned [V: [supply-chain.md](supply-chain.md)]). `compatibility.md` rewritten with the four columns of section 5. `core` tool profile evaluated in two clients (PR #140). `outputSchema` on about 20 tools. Icons regenerated from tokens and checked live. Dialogs: native window chrome, focus visuals, default and cancel buttons, high-contrast brushes. Pane: the accessibility items in section 10. |
| Acceptance checks | The Windows matrix in section 8, priority 1 cells, all recorded. A fresh Windows account installs and completes the read-only check; each of the five setup failures gives its recovery step. No unsigned-publisher prompt for the installer [U: Revit's own unsigned add-in prompt behaviour per year]. Keyboard-only run of the approve flow with NVDA. No control border under 3:1. |
| Proof required | One live record per Revit year. Signed artefacts verified with `Get-AuthenticodeSignature`. Accessibility run notes. Metrics baselines from section 9. |
| Rollback | Restore the previous add-in folder from the installer's backup (built in M0). A release can be withdrawn under [release-retirement.md](release-retirement.md). |

### M3. Enterprise and white-label

| | |
| --- | --- |
| Outcome | A BIM team installs for all users with settings users cannot loosen. A second brand builds from the same code and runs beside the first. |
| Effort | 20 to 35 days, plus counsel. Assumes the licensing questions in section 11 are answered before any closed build is promised. |
| Components | In order: (1) product identity generated from one file (replaces `ProductInfo.cs` constants and the hard-coded paths and port); (2) admin policy file with locks; (3) all-users install option and N-1 retention; (4) brand pack, validator and matrix build; (5) side-by-side test. |
| Acceptance checks | A locked approval mode cannot be changed by user settings, project settings or an environment variable. Two brands installed on one machine and loaded in one Revit: two ribbon tabs, two panes, two hubs on different ports; a read script runs in each (shared IronPython state); each pane keeps its own sign-in and storage (separate WebView2 user-data folders); each brand's server finds only its own Revit entry (separate registry folders); uninstalling one leaves the other working. **Leak search** of the second brand's installed files, `.addin` manifest, registry files, logs and About dialog finds none of the first brand's names, GUIDs, folder names, port, repository links, or the maintainer name, email address and profile links that are constants in `ProductInfo.cs` today [V]. |
| Proof required | The side-by-side run recorded on one Revit year. Written answers from counsel. |
| Rollback | Brand B is a separate installer and can be withdrawn alone. Policy is opt-in: no policy file means today's behaviour. |

## 7. The first three implementation tickets

### Ticket 1. Bind plans to the document and enforce it where the write happens

- **Why.** A plan approved for model A can run in model B after a tab switch [V: no check exists in the add-in; ADR 0017].
- **Scope.** Review and merge [PR #139](https://github.com/Sam-AEC/aec-model-bridge/pull/139) with four changes.
  - (a) *Fail closed.* In bridge mode, a plan with no binding cannot be approved. The PR allows an unbound plan when Revit cannot be read at drafting; keep that only for mock mode.
  - (b) *Enforce in the add-in.* The server adds the expected document identity to every mutating `/execute` payload of a bound plan. The add-in compares it with the active document on the UI thread before the command runs and refuses with kind `document_mismatch`, naming both documents.
  - (c) *No silent version skew.* Risk: a new server with an old add-in would call a plan "bound" while the old add-in ignores the field, so nothing enforces it. The add-in already writes `connector_version`, `protocol_version = 2` and `capability_digest` to its registry file and serves `/capabilities` [V: `BridgeServer.cs` lines 188, 359 to 363]. The add-in that has the check raises `protocol_version` to 3 and lists capability `doc_binding`. The server reads this when it pins the session and refuses every bound mutating call with kind `addin_too_old` when it is missing. Nothing is sent to Revit and no action is consumed. Reads keep working. The reverse case (old server, new add-in) behaves as today and gives no new protection; the installer ships both parts together.
  - (d) *Identity is more than the GUID.* Risk: `CreationGUID` is assigned when a file is created, so a Save As copy, a detached copy and possibly a template-born sibling can share it [U: not checked in Revit or in Autodesk's reference]. The binding therefore stores and compares three things: `CreationGUID`, the normalised full path (the central path for a workshared model), and the title. Any difference refuses. A document that was never saved has no path: it binds on GUID and title and the review shows "weak binding: unsaved document".
- **Files.** `security/approval.py`, `security/binding.py`, `providers/revit.py`, `Bridge/ExternalEventHandler.cs` (or the dispatch in `BridgeCommandFactory.Execute`), `revit-bridge-addin-tests`, `0017-…md` (status to Accepted), `demo-runbook.md` (remove "an approval is not tied to a document").
- **Acceptance checks.** Tests named in the architecture brief pass: claim refused when the document differs; refused when the live document cannot be read; unbound plan cannot be approved in bridge mode; approval older than the limit is expired; clock set backwards is expired; limit 0 disables. Add-in logic test: mismatching `expected_doc_guid` is refused before any transaction; a payload without the field behaves as today. A wrong document consumes no action. Plan hashes of stored plans do not change (pinned literals). Version skew: with a fake registry entry at `protocol_version` 2, a bound write makes zero HTTP calls to `/execute` and returns `addin_too_old`; a read still works. Identity: same GUID with a different path is refused; same GUID and path with a different title is refused.
- **Out of scope.** Instance identity for several Revit sessions (ADR 0014), `rollback_plan`, the pane showing the binding (M1).
- **Not provable without Revit.** Identity on workshared, detached and linked models, and whether copies share a `CreationGUID` [U]. M0 cannot close without the two-copies live test below.
- **Effort and rollback.** 2 to 4 days. Revert the pull request; the payload field is optional.

### Ticket 2. 64-bit element ids, and UniqueId beside every id

- **Why.** 34 id parses in `BridgeCommandFactory.cs` use `GetInt32()` (15 of them `element_id`) and cannot take ids above 2^31 [V]. Plans and reverts key on the integer id only, while findings carry only the UniqueId, so the id has to be looked up by hand [V: runbook step 3].
- **Scope.** One helper `ReadElementId(JsonElement)` using `GetInt64()`, used at all 34 places, plus the id-array parses (for example lines 2758 and 3448). Results return ids as 64-bit numbers. `plan_actions` accepts `element_uid` beside `element_id` and stores both in the action; the proof already has a `uid` field [V].
- **Files.** `Bridge/BridgeCommandFactory.cs`, `Bridge/PayloadJson.cs`, `revit-bridge-addin-tests`, `providers/approval_provider.py`, `security/proof.py`, tool descriptions.
- **Acceptance checks.** Logic test: id `3000000000` round-trips through the parse helper on `net48`, `net8.0` and `net10.0`. A source guard test fails if an `_id` property is read with `GetInt32()` again. A plan drafted with `element_uid` only is refused with a message that names the lookup tool, until uid resolution is implemented in the add-in. JSON schemas still say `integer`.
- **Out of scope.** Resolving UniqueId to an element inside the add-in for writes (M1, with preflight).
- **Effort and rollback.** 1 to 2 days. Mechanical; revert the pull request.

### Ticket 3. Result truth: read back, revert empty values, flag duplicate drafts

- **Why.** Findings 2, 3 and 4 of section 4.
- **Scope.**
  1. *Read-back.* After each successful `revit_set_parameter_value` in `execute_plan`, read the value again and store `read_back` and `matches` per element in the proof. `verification` becomes `verified`, `mismatch` or `unverified` (read failed). A mismatch marks the plan partly applied.
  2. *Recorded empty values.* `plan_actions` stores `before_has_value` from the read. `before_recorded` is true whenever the read succeeded, also for an empty value. `plan_revert` drafts "set back to empty" for those. The add-in's read returns `has_value` beside `value`.
  3. *Revert the executed subset.* Risk: a batch that was cancelled or failed half-way leaves some doors written and no way back except Undo. `plan_revert` accepts a plan with outcome `partial` and drafts a revert for exactly the actions in state `executed` (and, with read-back, whose value matched). Failed, abandoned and never-started actions are listed as excluded in the hashed review block. A still-running action blocks the revert until it is settled.
  4. *Before-value drift.* At claim time, read the current value; if it differs from the recorded before value, refuse that action as stale and consume nothing.
  5. *Duplicate drafts.* Compute an intent key (hash of document binding, tools, arguments and skips; no ids, no time). `plan_actions` returns `duplicate_of` when a pending or approved plan has the same key, and the pane and terminal tool show it. It warns; it does not block, because a deliberate second draft after a rejection is legitimate.
  6. *Kept mock driver.* `scripts/demo/mock_batch_edit.py`, the section 4 flow, run in CI.
- **Files.** `providers/approval_provider.py`, `security/proof.py`, `security/approval.py`, `approve_cli.py`, `Bridge/BridgeCommandFactory.cs` (read result), tests, [proof-and-revert.md](proof-and-revert.md).
- **Acceptance checks.** With a fake provider that stores values: proof shows 10 of 10 `matches`; a provider that writes a different value gives outcome `partial` and names the element. A plan that filled 10 empty values can be reverted and the revert sets them empty. A plan stopped after 4 of 10 gives outcome `partial`; its revert plan has exactly 4 actions and names the other 6 as not run. A value changed between drafting and execution is refused and the action stays unused. Two identical drafts: the second carries `duplicate_of`. The mock driver's stability table is asserted in a test.
- **Not provable without Revit.** Whether Revit accepts setting a text parameter back to empty, and whether `HasValue` is false for a never-set Mark [U]. Both are on the M1 live list.
- **Effort and rollback.** 4 to 6 days, as five small pull requests. Each is additive to the proof schema (`amb.proof/1` gains optional fields).

## 8. Windows and Revit test matrix, and the smoke commands

### Matrix

Priority 1 cells are required for M2. Priority 2 cells are sampled.

| Dimension | Values | Priority 1 | Priority 2 |
| --- | --- | --- | --- |
| Revit year and runtime | 2024 (`net48`, IronPython 2.7), 2025 and 2026 (`net8.0`, IronPython 3.4), 2027 (`net10.0`) | All four | Latest update of each year; 2025 or 2026 after a .NET 10 update [U] |
| Windows | 11 (current), 10 22H2 | 11 with every year | 10 with 2024 [U: which Windows versions each Revit year supports] |
| Install route | Signed installer per user; source build with scripts | Installer on every year | All-users install (M3); upgrade from the previous release; uninstall |
| Model | Canonical fixture, not workshared | Every year | Workshared local copy with a second user holding 2 doors; one linked model; a detached copy |
| Theme and scaling | Light, dark; 100 %, 150 %, 200 % | Light and dark at 100 % on every year; 200 % on one | Windows contrast theme on one year |
| Client | Pane only; Claude Desktop; VS Code | Pane on every year; one MCP client on two years | Cursor, Codex |
| Sessions | One Revit | Every year | Two Revit years open at once (ADR 0014); Revit restarted while the hub runs (LIVE-02) |

Each priority 1 cell records: Revit build, add-in version, commit, the M1 flow counts, the refused-write checks, and time to first read.

### Smoke commands

Taken from the repository's scripts and documents [V: script names and parameters read from `scripts/*.ps1`, [first-check.md](first-check.md), [fixture README](../fixtures/canonical-model/README.md), [acceptance README](../scripts/revit/acceptance/README.md)]. **Not executed in this session** (no Windows) [U]. Run from the repository root in PowerShell, on a test machine, with a disposable copy of the fixture.

```powershell
# 0. Record what is under test
git rev-parse HEAD; Get-Content VERSION

# 1. Build and logic-test the add-in for one year (no Revit needed)
.\scripts\build-addin.ps1 -RevitVersion 2026 -Configuration Release
dotnet test packages\revit-bridge-addin-tests -c Release -p:RevitVersion=2026
.\scripts\test-ironpython-runtime.ps1 -RevitVersion 2026

# 2. Python suite and stdio smoke test (mock mode, no Revit needed). Run from the package folder, as CI does.
python -m pip install -e "packages/mcp-server-revit[dev]"
Push-Location packages\mcp-server-revit; python -m pytest tests -q; Pop-Location

# 3. Install for that year. Close Revit first.
.\scripts\deploy-addin.ps1 -RevitYear 2026 -InstallManifest
#    or, for a built installer on a throw-away machine only:
#    .\scripts\test-installer.ps1 -Installer .\dist\AECModelBridge-Setup-1.5.0.exe -Year 2026 -AllowOverwrite

# 4. Start Revit 2026, open a clean project, open the pane. Then ask the hub for the setup check.
$panelToken = (Get-Content "$env:LOCALAPPDATA\AECModelBridge\panel-hub.token" -Raw).Trim()
Invoke-RestMethod "http://127.0.0.1:8787/diagnostics" -Headers @{ "X-AMB-Token" = $panelToken }
#    Expect ok = True, approval_mode = ask_first, every check ok.

# 5. Build the fixture in the open Revit, then run the read-only end-to-end tests
python scripts\revit\generate_canonical_test_model.py
$env:AEC_MODEL_BRIDGE_E2E = '1'
python -m pytest packages\mcp-server-revit\tests\e2e -m e2e

# 6. Read-only acceptance harness, pinned to this Revit process and document
#    (take pid, title and guid from revit_get_context; the document title must mark it as a scratch model)
python scripts\revit\acceptance\run.py --pid <PID> --expected-document "<TITLE>" --expected-guid "<GUID>" --run

# 7. Approval flow by hand, as in docs\demo-runbook.md steps 1 to 8. The person approves:
aec-model-bridge-approve list
aec-model-bridge-approve show <plan_id>
aec-model-bridge-approve approve <plan_id>      # type the plan id when asked; do not pass --yes
```

Step 7 is the first live write. Treat it as a test in its own right, on a throw-away copy.

## 9. Metrics

| Metric | Definition | How it is measured | Baseline today |
| --- | --- | --- | --- |
| First successful read | Time from the end of installation to the first successful read of the open document | Installer log time to first `revit_get_context` success in the audit log, on a fresh Windows account | **None. Needs a baseline** (M2). |
| First approved change | Time from first read to the first executed approved plan | Audit log: first check to first proof record | **None. Needs a baseline** (M1). No live run of the approval flow is on record. |
| Preview matches applied | Share of applied actions whose read-back value equals the previewed value | `matches` in the proof (ticket 3) | **Not measurable today**: the proof states values were not re-read [V]. Target 100 %; one mismatch blocks a release. |
| Recovery time | Time from a failure (bridge stopped, Revit restarted, dialog blocked, partial failure) to a known good state | Timed runs of four scripted failures | **None. Needs a baseline** (M1). LIVE-02 (stale chat connection after restart) is open [V]. |
| Duplicate prevention | Pending plans with the same intent key per document; duplicate QA issues per re-check | Intent key (ticket 3); issue store | **Measured in mock** [V]: plans 0 of 1 duplicates flagged (two identical drafts gave two pending plans); QA issues 0 duplicates on re-check (15 stayed 15). |
| Regressions | Failures on `main`; live smoke result per Revit year per release; defects found live after release | CI history; the per-year live records; `LIVE-nn` ids | CI: last `main` run green, 12 of 12 jobs [V]. Local: 3,135 passed [V]. Live smoke per year: 2024 read-only once (1.4.0), others never. |
| Wrong edits | Elements changed that were not in the approved plan | Parameter dump diff before and after, outside the plan's element list | **None. Needs a baseline** (M1). Target 0. |

Pilot go criterion, unchanged in spirit from the old priority 4: zero unintended changes, documented recovery, and a time saving against the same manual task measured with real coordinators.

## 10. Design system

A clickable reference for this section is [design/prototype.html](design/prototype.html). It is a design prototype with synthetic data. It is not shipped code and is not connected to Revit. What was checked on it is listed at the end of this section.

Direction: restrained and Revit-native ("Instrument" in the design brief). Neutral surfaces, one brand accent, state shown by shape and word, never by colour alone.

### Information architecture and navigation

- **Ribbon** is for entry and state: one large Review button that opens the pane, small Connect and Status, small Log, Settings and Help. No workflow happens in the ribbon.
- **Pane** is where work happens. A sticky header with the lockup, the active document and a connection chip. Three tabs: **Review** (findings, preview, approval, result), **Log**, **Settings**. Chat moves behind Review: it is an input to plans, not a destination.
- **Review is a sequence**: finding, preview, approval, result. One screen each. Approval cannot be reached before the preview.
- **Per-document state.** Plans belong to a document. When the active document changes, plans of another document are shown as "belongs to …, not active" and cannot be approved.

### Type, spacing and density

| Item | Value |
| --- | --- |
| Family | Segoe UI, then system UI. Ids, hashes and counts in a monospaced face with tabular figures. |
| Sizes | Body 13 px, meta 12 px, titles 15 px semibold. Sized in `rem` so Windows text scaling and zoom apply. Nothing below 11 px (the rail's labels are 10 px today [V: `panel/styles.css:268`]). |
| Spacing | 4 px grid: 4, 8, 12, 16, 24. Card radius 6 px. |
| Density | Comfortable: 32 px controls, 8 px row padding. Compact: 28 px controls, 4 px rows. Never under 24 px (WCAG 2.2 target size, level AA [U: page not opened; 44 px is the AAA figure]). |
| Pane width | Designed for 360 to 400 px. Reflows to one column; no horizontal scrolling. |

### Colour tokens

Three layers that are never mixed: core tokens (surfaces, ink, lines, five semantic colours), brand tokens (six values per theme, from the brand pack), and high contrast (brand colours are not used).

Core values are those of `design/tokens.md` and `panel/styles.css` [V], with two additions: `line-strong` for control borders, and an explicit high-contrast set.

| Token | Light | Dark | High contrast |
| --- | --- | --- | --- |
| `ink` / `ink-muted` | `#18202C` / `#5B6676` | `#E8EBEF` / `#C8CFD9` | `#FFFFFF` / `#E0E0E0` |
| `bg` / `surface` / `raised` | `#F2F5F8` / `#FFFFFF` / `#E9EEF4` | `#3B4453` / `#2F3846` / `#434D5C` | `#000000` / `#000000` / `#1C1C1C` |
| `line` (dividers only) | `#D3DAE3` | `#515C6B` | `#FFFFFF` |
| `line-strong` (control borders) **new** | `#737F90` | `#9AA5B5` | `#FFFFFF` |
| `danger` / `warning` / `success` | `#C23B2E` / `#A45F0B` / `#127A4B` | `#FCAA9F` / `#F7BA60` / `#5ED9A0` | `#FF9C91` / `#FFD166` / `#7CF0B4` |
| `info` / `pending` | `#2457C5` / `#6D3FB8` | `#A3C0F8` / `#D3BDF8` | `#9CC7FF` / `#E0CCFF` |
| Brand: `brand` (icons, accents) | `#0091A7` | `#3FC3D6` | `#5CE6FF` (core, not brand) |
| Brand: `brand-text` (text, focus ring) | `#046B80` | `#6FD8E6` | `#5CE6FF` |
| Brand: `primary-bg` / `on-primary` | `#046B80` / `#FFFFFF` | `#3FC3D6` / `#06222A` | `#FFFFFF` / `#000000` |

Computed contrast (WCAG 2.x relative luminance; computed in the prototype from the colours in use and read out with Playwright) [V]:

| Pair | Needs | Light | Dark | High contrast |
| --- | --- | --- | --- | --- |
| `ink` on `surface` / on `bg` | 4.5 | 16.38 / 14.97 | 9.89 / 8.21 | 21.00 / 21.00 |
| `ink-muted` on `surface` / `bg` / `raised` | 4.5 | 5.82 / 5.32 / 4.99 | 7.54 / 6.26 / 5.45 | 15.91 / 15.91 / 12.91 |
| `brand-text` on `surface` / on `bg` | 4.5 | 6.14 / 5.61 | 7.12 / 5.91 | 14.22 / 14.22 |
| `on-primary` on `primary-bg` | 4.5 | 6.14 | 7.86 | 21.00 |
| `danger` / `warning` / `success` on `surface` | 4.5 | 5.30 / 4.98 / 5.37 | 6.42 / 6.84 / 6.71 | 10.42 / 14.56 / 14.98 |
| `info` / `pending` on `surface` | 4.5 | 6.47 / 6.88 | 6.45 / 6.99 | 12.03 / 14.25 |
| `line-strong` on `surface` / `bg` / `raised` | 3 | 4.06 / 3.71 / 3.48 | 4.75 / 3.94 / 3.43 | 21.00 / 21.00 / 17.04 |
| `brand` on `surface` (icon accent) | 3 | 3.74 | 5.63 | 14.22 |
| `line` on `surface` (decorative) | none | 1.41 | 1.74 | 21.00 |
| Sample brand B: `brand-text` on `bg`; button label on fill | 4.5 | 7.89; 8.64 | 5.80; 7.93 | core values |

Findings behind the additions:

- `line` reaches only 1.41:1 (light) and 1.74:1 (dark) on `surface` [V]. Fine for dividers. Not enough for the edge of an input, select or checkbox, which needs 3:1. Hence `line-strong`.
- The design brief proposed `#7C8798` for dark `line-strong`. It gives 3.25 on `surface` but 2.70 on `bg` and 2.35 on `raised` [V: computed]. `#9AA5B5` passes on all three.
- `brand` `#0091A7` is 3.74:1 on white: good for icons and rings, not for text. Text uses `brand-text`.
- Windows contrast themes: under `forced-colors`, map to system colours (`CanvasText`, `ButtonText`, `Highlight`, `GrayText`) and keep borders. The panel has only two such rules today [V: `panel/styles.css:899`]. WPF dialogs switch brushes on `SystemParameters.HighContrast` [I].

### Icon rules

1. A neutral silhouette (slate on the light ribbon, near-white on the dark one), **one** block in the `brand` token, and at most one state badge. No gradients.
2. Two drawings per icon, one for the 16 px grid and one for the 32 px grid, each aligned to whole pixels. Never scale one to the other.
3. At 32 px the badge may hold a glyph (check, cross, clock). At 16 px the badge is a plain shape; a glyph there is about 3 px of noise. The shipped `pending_16_dark.png` shows the problem: its badge is about 6 px and the clipboard body blurs [V: image inspected].
4. State is a shape plus words in the tooltip ("Connected to Model-A, 1 plan waiting"). Colour repeats it and is never the only signal.
5. A one-colour version of every icon and of the logo exists and uses the current text colour. It is what high contrast shows.
6. The accent comes from the brand pack, so `scripts/make_ribbon_icons.py` takes it as input. Semantic colours are used only inside badges.
7. Counts are not drawn into icons. The ribbon has no badge control; a count goes into the button text ("Review (1)") [I: proposal].
8. The Cerberus mark stays inside its own feature. About uses the product mark (today About shows the Cerberus mark [V: `RIBBON_ICONS.md`], against `tokens.md`).

Ribbon background colours are assumed (`#F0F0F0` light), not sampled from a Revit screenshot [U]. Sample them in Revit 2024 and 2027 before the icon set is final.

### Motion

120 ms for hover and press, 180 ms for a view change, no looping animation except a determinate progress bar. Everything is switched off under `prefers-reduced-motion` [V: already in `panel/styles.css:116`]. A toast stays 6 seconds and pauses on hover or focus.

### Keyboard, focus, scaling and screen-reader names

| Topic | Rule |
| --- | --- |
| Order | Header, tabs, content, actions. Tabs are one stop; arrow keys, Home and End move between them. |
| Focus | 2 px ring in `brand-text` with a 2 px offset, visible in all themes. The sticky header must not cover the focused control (`scroll-padding-top`). After a step change, focus moves to the new step's heading. After a dialog closes, focus returns to the control that opened it. |
| Activation | Enter and Space on the focused control only. No default button on the approval step. No single-key shortcuts: Revit owns the keyboard and WebView2 inside Revit can lose keys to it [I]. |
| Disabled | A disabled approval button stays focusable, says why in text beside it, and is tied to that text with `aria-describedby`. |
| Names | The action plus its object plus the document: "Approve plan: set Mark on 10 doors, canonical_test_model.rvt". Icon-only controls always have a name. In WPF, `AutomationProperties.Name` on every such control (today only Close and the logo have one [V: `ModernDialog.xaml` lines 131, 155]). |
| Live regions | Success and progress: polite (`role="status"`). Failure, disconnect, stale plan: `role="alert"`, persistent, never a toast. |
| Scaling | Layout in `rem` and wrapping rows. No fixed-height header or footer rows. The dialog has fixed 64 and 76 px rows [V: `ModernDialog.xaml` lines 117, 119]; that they clip at 150 to 200 % is [I]. |
| Dialogs | Native window chrome, a default and a cancel button, Tab cycles inside. The current dialog is borderless and transparent with a hand-drawn close button and no focus visual [V: `ModernDialog.xaml` lines 14, 15]. |

### Long and localised labels

- Buttons wrap; they never truncate. Action rows wrap to a second line.
- File names use a middle ellipsis and keep the full name in the tooltip and the accessible name.
- Design for 40 % longer strings. The prototype has a pseudo-locale that lengthens every label and uses a 74-character file name.
- No text in images. Numbers and ids are not translated. Strings live in one table per surface (pane, add-in, installer), which the brand pack can override per key.
- The repository has README translations in 16 languages but the pane and add-in are English only [V: `docs/i18n`]. Localising them is not planned before M3.

### Surfaces mapped to what Revit offers

| Need | Revit surface | API | State in the add-in |
| --- | --- | --- | --- |
| Entry points and connection state | Ribbon tab and panels; 32 px `LargeImage`, 16 px `Image`; tooltip; F1 help | `CreateRibbonTab`, `CreateRibbonPanel`, `PushButtonData`, `SetContextualHelp` | Exists [V: `Bridge/App.cs` lines 100 to 310] |
| The whole review workflow | Dockable pane, docked right, hosting WebView2 | `RegisterDockablePane`, `IDockablePaneProvider` | Exists [V: `UI/BridgePanelProvider.cs`] |
| Theme | Revit light or dark; Revit does not theme hosted content | `UIThemeManager.CurrentTheme`, `ThemeChanged` (2024 and later) | Exists [V: `BridgePanelProvider.cs:39`]. `BridgePanel.xaml` paints a light background before the page loads, which flashes in dark theme [I: design brief]. |
| Show the affected elements | The model view itself | `UIDocument.Selection.SetElementIds`, `ShowElements`; temporary view overrides | Selection tool exists; in-model preview is unverified live ([preview-in-model.md](preview-in-model.md)) |
| A blocking question or a failure the pane cannot show (the pane itself failed to load, a document is closing with a plan still running) | Native `TaskDialog` with command links | `TaskDialog`, `AddCommandLink` | Not used. `tokens.md` currently forbids it and the add-in draws its own dialog [V: grep found no `TaskDialog`]. Proposal: allow `TaskDialog` for these cases, because it is keyboard-accessible, themed and announced by screen readers for free [I]. |
| Short confirmations | Revit has no public toast or status-bar API [I] | Toast drawn inside the pane | Proposal |
| Approval | Stays a button in the pane and the terminal tool, sent with the plan hash, as today. Not a modal dialog: the reviewer must be able to click into the model while reading. | Existing hub route | Exists; contract unchanged |

### What was checked on the prototype

Headless Chromium through Playwright, `file://` load, 1280 by 900 and 400 by 900 [V]:

- All fourteen states render with no console error and no network request other than the file itself. They include the three states the navigation rules above need: a plan that belongs to another document ("belongs to …, not active"), a duplicate draft, and a draft whose values are already in the model; and a stale plan that shows which element changed, with the value at preview, the value now and the value the plan wanted. The page carries a content security policy of `default-src 'none'`.
- The full flow by mouse: setup, reconnect, finding, plan, preview, approval (blocked until the box is ticked), applying, partial failure, retry plan, final audit. Also stale plan to a refreshed plan (9 changes, 3 skipped, new plan id), disconnected to reconnected with the plan kept, and cancel during applying.
- Keyboard only: tick the box with Space, Tab to the approve button, Enter; tabs with arrow keys and End; the dialog opens with Enter, closes with Esc and returns focus; theme and brand switch with arrow keys.
- In every state: every interactive element has an accessible name, no duplicate ids, no broken `aria-` references, no control smaller than 24 px, one `h1`.
- Reflow: no horizontal scrolling at 380 px wide in any state, in three variants each (default, dark with the second brand, pseudo-locale with compact density), and none at 400 px with 200 % text size.
- Text size: the smallest rendered text in any state at 380 px is 11 px. An earlier draft had two places under 11 px (a `small` element at the browser default, and labels inside a scaled drawing); both were fixed in the prototype, so the rule above holds there.
- Contrast: no failing pair in any of three themes for both brands. The deliberately faulty third pack triggers seven fallbacks and one build error message.

Not checked: a real screen reader, Windows contrast themes, WebView2 inside Revit, real ribbon rendering at 16 px on a 100 % display, colour-blind simulation [U].

## 11. White-label design

Goal: two brands from one codebase that can be installed side by side. This is M3 and depends on counsel.

### Layers

| Layer | Holds | Who owns it | May a brand change it |
| --- | --- | --- | --- |
| Brand pack | Names, logo files, six brand colours per theme, ribbon tab name, copy strings, links, ids, paths, default ports | Brand owner, at build time | Yes: this is the brand |
| Core semantics | Danger, warning, success, info, pending colours; state shapes; approval wording; high-contrast theme | Core | No |
| Deployment policy | Install scope, approval mode ceiling, dev mode allowed, allowed folders, ports, update channel | The customer's administrator | No |
| MCP contract | Tool names, schemas, plan and proof formats | Core, frozen | No. Only the server's registry name and title differ. |

### Brand pack schema (`brand.json`, `schemaVersion` 1)

```json
{
  "schemaVersion": 1,
  "id": "quay-model-desk",
  "product":  { "name": "Quay Model Desk", "short": "Quay Desk", "ribbonTab": "Quay Desk", "publisher": "…", "vendorId": "QUAY" },
  "ids":      { "addInGuid": "…", "dockablePaneGuid": "…", "innoAppId": "…", "mcpServerName": "quay-model-desk", "mcpbName": "…", "vscodeId": "…" },
  "paths":    { "programData": "QuayModelDesk", "localAppData": "QuayModelDesk", "workspaceDefault": "Quay Model Desk" },
  "network":  { "hubPort": 8797 },
  "assets":   { "mark": "mark.svg", "markOneColour": "mark-mono.svg", "ico": "icon.ico", "installerBitmaps": ["wizard.bmp", "wizard-small.bmp"] },
  "tokens":   { "light": { "brand": "#B0307A", "brand-text": "#8A1F5C", "primary-bg": "#8A1F5C", "primary-hover": "#6E1749", "on-primary": "#FFFFFF", "tile": "#2B0A1D" },
                "dark":  { "brand": "#F08CC2", "brand-text": "#F7B3D8", "primary-bg": "#F08CC2", "primary-hover": "#F7B3D8", "on-primary": "#2B0A1D", "tile": "#2B0A1D" } },
  "strings":  { "en": { "pane.title": "…" } },
  "links":    { "docs": "…", "support": "…", "licence": "…" },
  "legal":    { "noticeFile": "NOTICE", "trademarkFile": "TRADEMARKS.md" }
}
```

"Quay Model Desk" is a made-up sample brand used in the prototype. The prototype applies both brands through one function and one set of CSS inputs; switching brand changes brand tokens, names, logo and default port and nothing else [V: prototype].

### Fallback rules

| Case | Build of a release | At run time |
| --- | --- | --- |
| A colour is missing | Core default for that key, with a warning | Same |
| A colour fails contrast (`brand-text` under 4.5:1 on `bg` or `surface`; button label under 4.5:1 on its fill; `brand` under 3:1) | Build fails | Core default for that key or pair, warning in the log and in Settings |
| A logo file is missing | Build fails | A mark generated from the button colours |
| A string is missing | Core English string | Same |
| `ids`, `paths` or `network` missing or equal to another installed brand | **Build fails. Never a fallback.** A shared GUID, folder or port is how two brands break each other. | Refuse to start, with a message |
| High contrast or Windows contrast theme | Not applicable | Brand colours are not used; the name and one-colour logo carry the brand |
| Unknown `schemaVersion` | Build fails | Core default brand, warning |

A brand pack can never change a semantic colour, the approval wording or any behaviour.

### Settings precedence and migrations

Values are resolved from low to high, then administrator locks are applied last:

1. Built-in defaults
2. Brand pack
3. Administrator policy: `%ProgramData%\<brand>\policy.json`, writable only by administrators
4. User settings: `%LOCALAPPDATA%\<brand>\settings.json`
5. Project settings: `.<brand>\project.json` in the workspace
6. Environment variables (`MCP_REVIT_*`), which is how MCP clients configure the server today

Rules:

- The administrator can mark a key as **locked**. A locked key ignores layers 4 to 6.
- Security keys (approval mode, dev mode, allowed folders, approval time limit) are **ceilings**. A higher layer may only tighten them: a project can switch to look-only, never to auto. A project file can arrive with a model from someone else, so it is never trusted to loosen anything.
- For non-security keys (rule pack, naming rules) the project wins over the user, because office standards beat personal preference.
- Settings shows where each value came from and whether it is locked.

Migrations:

- Every file has a `schemaVersion`. Migration happens when the file is read, in memory. The file is rewritten only when the user or administrator saves, and the previous file is kept as `.bak`.
- Unknown keys are kept, not dropped. A file with a newer version than the program understands is read for the keys it knows and is never rewritten.
- The installer never overwrites policy or user files. Today `default.json` is replaced on every install [I: distribution brief]; M3 moves defaults into the program and leaves that folder to the administrator.
- Existing users: on first run after M3, today's `default.json` values and environment variables are read as before; nothing is moved without a prompt.

### Side-by-side installs: what must differ per brand

| Item | Value today | Evidence | Per brand |
| --- | --- | --- | --- |
| Revit `AddInId` | `6721F048-9A81-4DE6-8543-B485A6329B92` | [V: `AECModelBridge.addin`] | New GUID. Revit keys add-ins by it [U: forum source]. |
| `.addin` file name, `<Name>`, `VendorId` | `AECModelBridge.addin`, "AEC Model Bridge", `SAMA` | [V] | Distinct |
| Dockable pane GUID | `4E6D3F28-1C74-4B41-9B6E-7B1D3A2C0C4F` | [V: `BridgePanelProvider.cs:10`] | New GUID |
| Ribbon tab name | "AEC Bridge" | [V: `App.cs`, `tokens.md`] | Distinct; two tabs with one name collide [I] |
| Assembly name and namespace | `AECModelBridge`, namespace `RevitBridge` | [V: `RevitBridge.csproj` lines 7, 8] | **Collides today.** Two brands with the same assembly name in one Revit process resolve to whichever loaded first [I]. Distinct assembly name per brand. |
| Installer `AppId` | `D41A24F3-87B1-4A51-9F31-30919E371C25` | [V: `AECModelBridge.iss:21`] | New GUID |
| Program folder | `C:\ProgramData\AECModelBridge` (fixed; bundled Python path hard-coded) | [V: `.iss:31`, `PanelHubLauncher.cs:276`] | **Collides today:** a second brand's installer would overwrite the first brand's binaries and Python. `%ProgramData%\<brand>` |
| Per-user folder (registry, token, logs, WebView2 data) | `%LOCALAPPDATA%\AECModelBridge` | [V: `BridgeServer.cs:349`, `HubClient.cs:41`, `BridgePanel.xaml.cs:116`] | `%LOCALAPPDATA%\<brand>`. With a shared registry folder each brand's server would find the other brand's Revit entry and token; with a shared WebView2 folder the panes share storage [I]. |
| Script engine in the Revit process | IronPython 2.7.12 or 3.4.1 and its standard library, loaded by the add-in | [V: csproj lines 56 to 61] | Both brands load IronPython into one process. Ship the same IronPython version in every brand, or verify isolation per Revit year [U]. |
| Hub port | 8787, override by environment variable | [V: `HubClient.cs:131`, `PanelHubLauncher.cs:42`] | Brand default (sample brand: 8797), same override |
| Add-in bridge port | Picked by Windows per Revit session | [V: `BridgeServer.cs:78`] | Nothing to do; the registry folder separates brands |
| Workspace folder | `Documents\AEC Model Bridge` | [V: old roadmap, `WorkspaceDirectory.cs`] | `Documents\<brand name>` |
| MCP server name | `aec-model-bridge` | [V: stdio `initialize`] | Distinct; tool names stay the same |
| Product strings and links | Constants in `ProductInfo.cs`: product name, repository links, and the maintainer's name, email address and profile links | [V] | Generated from the brand pack. No personal details in any branded build; part of the leak search. |

One codebase, one installer per brand from a matrix build. A single installer for several brands is rejected: it makes clean uninstall of one brand hard and mixes signing identities [I].

### Licensing questions that need counsel

Not legal advice. These are the questions, not the answers.

1. The code is GPL-3.0-or-later with a Revit linking exception, or a commercial licence ([LICENSING.md](../LICENSING.md)) [V]. Can a closed, rebranded distribution exist at all, and does it need a commercial grant from every copyright holder? What is the status of the draft contributor agreement in `docs/legal`?
2. Is the Revit linking exception valid and sufficient under GPL section 7, also for forks, and how does it sit with Autodesk's API and licence terms?
3. What notices and obligations apply to the bundled parts in an installer: IronPython and its standard library, the WebView2 runtime, embedded Python, `certifi` (MPL-2.0)?
4. IfcOpenShell is LGPL-3 and bundled as a replaceable package [V: `NOTICE`]. What must a proprietary brand do to keep it replaceable?
5. Trademark: can "AEC Model Bridge" and the Pier mark be registered, and who owns the mark (its authorship is not documented [V: distribution brief])? Is "revit" in tool names and registry listings acceptable use of Autodesk's mark?
6. For a customer's brand: who owns the logos and fonts, what permission is needed, and what do Autodesk App Store terms require?
7. Code signing: must the certificate holder match the publisher name shown for each brand?

## 12. Claims still unverified

| Claim | What would verify it |
| --- | --- |
| The approval flow, the native parameter writers on the current build, rollback, partial failure and revert work in live Revit | M1 live run |
| The add-in loads and the flow works on Revit 2025, 2026 and 2027; 1.5.0 works on 2024 | M2 live runs |
| A never-set Mark reads as "no value" in Revit, and a text parameter can be set back to empty | One live read and write in M1 |
| Document identity (`CreationGUID`, central path) is stable for workshared, detached and linked models | Ticket 1 live observation; M1 workshared variant |
| PR #139, #138 and #140 do what their descriptions say | Code review; their CI runs passed [V] but the code was not read here |
| Revit 2027 on .NET 10, a .NET 10 update for 2025 and 2026, the 2027 add-in folder change and add-in isolation | Autodesk's own documentation |
| Autodesk's Revit MCP server scope, supported versions and approval model; every competitor detail | The vendors' own pages or a trial |
| MCP specification details beyond protocol `2025-11-25` and SDK 1.30.0 behaviour seen here (output schema validation, elicitation, tasks) | The specification site; a contract test |
| Revit's unsigned add-in prompt per year; SmartScreen behaviour with and without a certificate | A signed and an unsigned install on a clean machine |
| Real ribbon background colours; icon legibility at 16 px on a 100 % display | Screenshots from Revit in both themes |
| The Windows smoke commands in section 8 run as written | Run them on Windows |
| The prototype works with a screen reader and Windows contrast themes | NVDA and a contrast-theme run |
| Time saved for coordinators | A pilot. None has been run. |

## What this page replaced

- The priority table of 2026-10-09: priorities 0 to 2 are M0 and M1, priority 3 is workflow 3 and M2, priority 4 is workflow 2 (PR #138) and M2.
- "First demo scope": the step-by-step script lives in [demo-runbook.md](demo-runbook.md). The snapshot file-name contract described there (add-in writes `snapshots/{GUID}.json`, both sides use one workspace rule) is still unverified against a compiled add-in in live Revit.
- "Document identity checks are not implemented": still true on `main`; implemented in open PR #139.
- The session hand-over note `bridge-upgrade-handoff.md` was deleted in the documentation clean-up. Its three open next steps are listed under M1.
- "Finish the first demo before adding more integrations" stands.
