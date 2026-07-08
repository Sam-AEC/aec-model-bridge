# Next Agent Handover

**Latest session:** 2026-07-08 (third session same day) — implemented the panel→hub wiring that the previous session identified as fake. Code changed, tests added, both C# targets build, all committed to `development`. Nothing deleted.

**Read `git log` before trusting any summary here, including this one.** Two things have already been true today: a batch of commits claimed Phases 0–17 complete before anyone checked, and this file's own previous version called the panel "real plumbing around fake data" — both turned out to need correction on inspection, not blind trust.

## What I did this session

Closed the exact gap the previous handover named: the panel could receive clicks but never called a real hub tool.

1. **Designed the transport.** MCP is stdio-only; a WebView2 page can't launch/talk to it. `PLUGIN_APP_ARCHITECTURE.md` §2 already said the panel should reach "the hub via localhost" — so I added `panel_server.py`, a loopback-only (127.0.0.1) HTTP server exposing `GET /health` and `POST /execute {tool, arguments}`, running the exact same `ProviderRegistry` + `ApprovalGate` checks as the stdio server. New console script: `aec-model-bridge-panel-server`.
2. **Refactored for reuse, then fixed what the refactor exposed.** Moved provider-registry construction out of `mcp_server.py` into `registry_factory.py` so the new server doesn't duplicate ~60 lines. Along the way found that `revit_mcp_server/__init__.py` eagerly imported `mcp_server` (building a full registry — Speckle/APS OAuth, a Rhino bridge health probe, ModuleRegistry filesystem discovery — as a pure import side effect) purely to re-export an unused `run_server` alias nothing in the codebase actually calls. Made it lazy (`__getattr__`); confirmed by a manual smoke test that only one registry gets built now, not two.
3. **Tested the hub side for real** (`tests/test_panel_server.py`, 7 tests): health, executing a real read-only tool end-to-end, unknown-tool/missing-field/unknown-path error shapes, the ApprovalGate correctly rejecting a mutating call with no plan, and a full `plan_actions → approve_plan → execute_plan` round trip driven purely over HTTP — the same shape the C# side uses.
4. **Wired the C# side.** Added `HubClient.cs` (POSTs to the shim, parses the `{ok, result|error}` envelope) and rewrote `BridgePanel.xaml.cs`'s `OnWebMessageReceived` to parse the panel's message type and dispatch: `qaqc.runHealthCheck → qaqc_checker_run_check`, `plans.refresh → list_pending_plans`, `plan.approve/plan.reject → approve_plan/reject_plan` (then a plans refresh), `reports.exportExcel → report_generator_export_excel`. Hub-down or tool errors post a `tool.error` message instead of silently doing nothing. Needed one new assembly reference (`System.Net.Http`, net48 only — not auto-referenced there unlike net8/net10).
5. **Removed the fixture data.** `panel/app.js`'s hardcoded `plan_demo_01`/`f-001`/`r-001` arrays are gone (state starts empty); added `findings.updated`/`plans.updated`/`reports.updated`/`tool.error` handlers that map the hub's raw result shapes (e.g. QA/QC's `{rule_id, severity, element_uid, message}`) into what the render functions expect.
6. Verified both C# targets build clean (net48: 0 errors/85 warnings; net8/Revit 2025: 0 errors) and the full Python suite passes (214 passed, 4 skipped, ruff clean) after every commit.

**Honest limit of what's proven:** the JSON contract between `HubClient.cs` and `panel_server.py` is verified two ways — `test_panel_server.py` exercises the exact request/response shapes, and both C# targets compile against the real types — but nobody has run this against a live Revit process with WebView2 actually rendering the page and a human clicking the button. That's the boundary of what's provable in this environment; say so plainly if asked whether the panel "works."

## The gap this session did NOT close (the real next task)

**Nothing starts `panel_server.py`.** The C# side now calls `http://127.0.0.1:8787/execute` assuming a hub is listening there, but no code launches it — a user would have to manually run `aec-model-bridge-panel-server` in a terminal before opening the panel in Revit. Wiring the button-to-tool path was necessary but not sufficient; the hub process lifecycle is the remaining piece. Concretely, the add-in needs to (most likely in `App.cs`'s `OnStartup`, alongside where it already starts `BridgeServer`):

1. Check if something is already listening on the panel port (`GET /health`); if not, launch `aec-model-bridge-panel-server` as a child process (`Process.Start`, needs the right Python interpreter/venv resolution — check how `scripts/build-addin.ps1` or the install docs currently expect Python to be provisioned, since D-010 in `DECISIONS_AND_RISKS.md` decided on a bundled runtime for the installer but that isn't built yet).
2. Decide shutdown behavior: kill the child process on `OnShutdown`, or leave it running as a background service? (Leaving it running means panel reopens are instant; killing it is cleaner but slower to reopen.)
3. Surface hub-launch failures to the user somewhere sane — probably a `tool.error`-style panel message on first failed `/health` check, reusing the pattern already in `BridgePanel.xaml.cs`.

Secondary, smaller, independently valuable if picked up first: decide and implement the Navisworks build story (`packages/navisworks-bridge-addin` still can't build in any environment without a paid Navisworks install and no NuGet fallback exists — needs Sam's input, see D-011/D-012).

## What I did NOT change

- Did not implement hub-process launching (above — this is the real next task).
- Did not wire `chat.message`, `settings.save`, `reports.open`, or `reports.refresh` — no corresponding hub tool exists yet for the first and last, and the middle two are local-only concerns. Left exactly as before (post to host, no round trip).
- Did not touch `navisworks-bridge-addin`'s build story.
- Did not re-verify Phases 5–15 beyond what earlier verification already covered.

## Exact next prompt

> Read docs/product/NEXT_AGENT_HANDOVER.md. The panel now calls real hub tools via panel_server.py's HTTP shim, but nothing launches that Python process - a user would have to start `aec-model-bridge-panel-server` manually. Implement hub process lifecycle management in the C# add-in (likely App.cs's OnStartup/OnShutdown, alongside where BridgeServer already starts): check if the panel port is already alive via /health, launch the process if not, decide and implement a shutdown policy, and surface launch failures to the panel via the existing tool.error message pattern. Check how Python is expected to be provisioned today (build/install docs, D-010 in DECISIONS_AND_RISKS.md) before assuming a bare `python`/pipx invocation will work on a clean machine. Test what's testable, build both C# targets, commit incrementally, no Co-Authored-By trailers.
