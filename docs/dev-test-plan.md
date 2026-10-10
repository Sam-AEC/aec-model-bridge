# Dev branch test plan (Windows + Revit)

This is the plan for testing the `dev` branch by hand. `dev` is `main` plus a
set of open pull requests merged together, so nobody has run it end to end.
Everything here is **UNVERIFIED** unless a line says otherwise. The only things
checked so far are the Python unit tests and CI on Linux and Windows runners.
None of that touches a real Revit.

Fill in the results table at the end as you go. Treat every difference from
"working looks like" as a finding, not as something to explain away.

Record before you start: Revit year, `git rev-parse HEAD` of the dev checkout,
date, name of the model you tested on.

## What is on dev

Merged into `dev` on top of `main`, as merge commits, in this order: #95
(CreateTransaction fix), #98 (add-in and hub contract test), #93 (panel shim
Host/Origin/Content-Type checks), #94 (shared client, lazy imports), #96
(community health files), #100 (third-party notices), #97 (distribution
prerequisites), #76 (model bloat), #77 (sheet and view audit), #78 (model
changes), #81 (door and room consistency), #84 (naming checker), #69, #71, #74,
#65 (rule packs), #61 (pyRevit bridge), #64 (preview in model), #60 (panel
first-run check).

Not on dev: #92 (panel token, on hold because it breaks multi-Revit) and #99
(approval v2, under security review).

Because #95 and #64 are now in, parts of
[demo-runbook.md](demo-runbook.md) that say "open PR, not merged" are out of
date on this branch.

## A. Install from the dev branch

You need a build, because the dev add-in is not in any release. Requirements are
in [install.md](install.md#requirements): Windows, Python 3.11+, Git, the .NET
SDK for your Revit year (.NET 8 for 2025 and 2026, .NET 10 for 2027, .NET 8 SDK
plus the .NET Framework 4.8 developer pack for 2024).

Close Revit first. If you installed a release with the installer, uninstall it
or expect the source install to overwrite the add-in files.

```powershell
git clone https://github.com/Sam-AEC/aec-model-bridge.git
cd aec-model-bridge
git checkout dev
git rev-parse HEAD            # write this down

py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e packages/mcp-server-revit

$RevitVersion = "2026"        # your Revit year
.\scripts\package.ps1 -RevitVersion $RevitVersion
.\scripts\install.ps1 -RevitVersion $RevitVersion
```

These commands are copied from [install.md](install.md#install-from-source) and
the parameter blocks of `scripts/package.ps1` and `scripts/install.ps1`. Nobody
has run them from the dev branch. If `package.ps1` fails, `.\scripts\build-addin.ps1 -RevitVersion $RevitVersion`
builds the add-in only. Note the first error.

Checks:

1. `%APPDATA%\Autodesk\Revit\Addins\<year>\AECModelBridge.addin` exists, and
   `C:\ProgramData\AECModelBridge\bin\<year>\` has fresh files (check the
   timestamps are from now).
2. Start Revit, open a project. The **AEC Bridge** tab shows.
3. Bridge health (from install.md):

   ```powershell
   $registry = Get-ChildItem "$env:LOCALAPPDATA\AECModelBridge\registry\revit-*.json" | Select-Object -First 1
   $switch = Get-Content $registry.FullName -Raw | ConvertFrom-Json
   Invoke-RestMethod "$($switch.endpoint)/health"
   ```

   Working looks like: `status` is `healthy` and `revit_version` is your year.
4. Connect your MCP client to the dev checkout, using the `.venv` Python and
   `-m revit_mcp_server.mcp_server`, `MCP_REVIT_MODE=bridge`, and a workspace
   folder that exists (see [install.md](install.md#configure-an-mcp-client)).
   Ask the client to list tools. Working looks like: the new tools in section D
   appear.
5. Optional, no Revit needed: from the checkout, with the venv active,
   `cd packages\mcp-server-revit; $env:PYTHONPATH="src"; python -m pytest tests -q --ignore=tests/e2e --deselect tests/test_wheel_contents.py`.
   On Linux this gave 749 passed, 2 skipped. Record your number.

## B. First: the minimal safe write test

This is the first real write against Revit since the `CreateTransaction` fix
(#95). On `main` that method called itself, so any write would have recursed
until Revit crashed. Save everything in other Revit sessions first. Do it on a
**scratch copy** of a model, never a project file.

1. Make a copy of a small model and open the copy. Save as a new name if
   needed. Close other Revit documents.
2. Take a snapshot (`revit_extract_snapshot`). Note the `snapshot_id`.
3. Pick **one** element with an editable text parameter, for example one door's
   `Comments`. Note its element id and the current value.
4. Ask the assistant to plan exactly one `revit_set_parameter_value` on that
   element (parameter `Comments`, value `dev-test-1`) using `plan_actions`.
   Do not let it execute.
5. In the Revit panel, open the plan. Press **Approve** on it.
6. Ask the assistant to execute the plan (`execute_plan`).
7. In Revit, read the parameter in the Properties palette.
   - Working looks like: value is `dev-test-1`, and Revit did not hang or
     crash.
   - Failure signs: Revit freezes or closes (the old recursion), an error
     in the panel, or the value is unchanged.
8. Press Ctrl+Z once in Revit. Read the parameter again.
   - Working looks like: back to the original value.
   - If not, note how many undo steps it took. The runbook warns this may not be
     one.
9. Record: pass or fail for the write, pass or fail for undo, any message text,
   and `%APPDATA%\AECModelBridge\Logs\bridge.jsonl` lines around the time.

Stop here and report if step 6 or 7 fails. Do not continue to the demo.

## C. Demo runbook

Follow [demo-runbook.md](demo-runbook.md) step by step: step 0 (build the
fixture), snapshot, ask, plan, preview, approve, execute, verify, undo, and the
rejected-plan run. Differences on this branch:

- Writes are now possible because of #95. Only do steps 6 to 8 after B passed.
- Preview in the model (#64) is merged. Step 4 can use it: see
  [preview-in-model.md](preview-in-model.md). UNVERIFIED in Revit.
- Expected baseline from the manifest: 12 doors without Mark and 3 rooms
  without Number, 15 findings in total. Nobody has recorded this on a live
  model.
- `plan_revert` after executing: the doors started empty, so expect it to
  behave as the runbook describes.

Record the "Record for each run" items from the runbook alongside the table
below.

## D. The new tools, one by one

How to run each: ask the assistant in plain words, or call the tool by its
full name. All of these are read-only unless noted. Tool name is
`<module>_<tool>`. Take a **fresh snapshot of the real model** first and pass
its `snapshot_id`. Many tools can also run on built-in sample data when you
leave the id empty or run in mock mode. Do not count a sample-data result as a
live test.

**What "not enough data" means.** The add-in's snapshot does not yet carry
every field these checks would like. When a snapshot lacks a field, the tool is
meant to say so ("Not enough data ...") and skip that check, rather than guess
or report zero problems. That is a correct, honest result today. A wrong result
is: a clean bill of health that hides a skipped check, a crash, or numbers that
do not match the model. Write down any "not enough data" text exactly, so the
snapshot can be extended.

| Tool | Run | Working looks like | Honest "not enough data" looks like |
|---|---|---|---|
| `model_bloat_audit` | Snapshot id; optional `large_type_threshold`, `max_items` | Counts of unused families and types, in-place families, families with very many types, imported CAD, and a cleanliness estimate. Counts match what you see in Revit's Purge Unused / Manage Links (spot check two). Nothing is deleted. | Notes like "Not enough data for '<check>'" and "Model cleanliness: not rated". Check that skipped checks are named. |
| `sheet_view_audit_run_audit` | Snapshot id | Empty sheets, unplaced views, duplicate sheet numbers, missing sheet parameters listed with ids you can find in Revit. | "Not enough data in this snapshot for: <list>" if the snapshot lacks sheets or views. |
| `model_changes_list_snapshots`, then `model_changes_compare_snapshots` | Take a snapshot, change something in Revit (add a door, rename a room, move a wall), take a second one. Compare `previous` and `latest`, or pass ids | The list shows both snapshots. The compare names what was added, removed, changed. Your change appears. | Text that it cannot tell whether anything moved or rotated. With only one snapshot it should say there is nothing to compare, not invent changes. |
| `schedule_consistency_check_doors_and_rooms` | Snapshot id | Duplicate or missing door Marks, missing From/To Room, rooms with missing numbers or zero area. Counts match your door and room schedules. | "Not enough data" for From Room / To Room, or for whether zero-area rooms are placed. The door-to-room checks may be reported as NOT run. |
| `naming_checker_list_example_conventions`, then `naming_checker_check_names` | List the example conventions, pick one, check a snapshot against it | A list of names that break the convention, by element kind (views, sheets, levels, and so on). | "Not enough data for view names" if the snapshot has no or partial views. |
| `warnings_triage_review_warnings` | Live Revit only, a model that has warnings (Manage > Inspect > Review Warnings) | Warnings grouped by type and ranked by element count. The top group matches Revit's own warning dialog. | An empty or short result with a clear reason if the model has no warnings. Zero warnings in a model that has them is a bug. |
| `links_worksets_audit_audit` | Snapshot id, model with a Revit link and worksets | Linked models and worksets listed, with problems like unloaded links or elements on odd worksets. | Notes for fields not in the snapshot. Non-workshared models should say so, not error. |
| `clash_triage_match_clashes`, `clash_triage_list_clash_issues` | Needs a Navisworks clash test export (the `clash_results` input). Without one, skip and mark N/A | Each clash matched to the Revit elements it involves, grouped, recorded as issues you can list. | Clashes that cannot be matched say so. See [clash-triage.md](clash-triage.md). |
| `bcf_exchange_export_bcf`, `bcf_exchange_import_bcf` | Export the recorded issues from the core QA run to a `.bcfzip` in the workspace. Import it back. Open it in a BCF viewer if you have one | A `.bcfzip` appears in the workspace (this writes a file, not the model). Import returns the same titles and status. See [bcf-exchange.md](bcf-exchange.md). | Export with no issues should say it has nothing to write. |
| Review pack: `report_generator_build_review_pack` | After a QA run and a snapshot. Check the tool's inputs with your client first | A review pack file in the workspace that opens, with findings that match the QA list. | Missing sections named, not silently blank. |

Also quickly look for the other merged modules in your client's tool list:
rule packs (`qaqc_checker_list_rule_packs`, `_validate_rule_pack`,
`_import_rule_pack`, `_export_rule_pack`, see [rule-packs.md](rule-packs.md))
and the pyRevit bridge (see [pyrevit-bridge.md](pyrevit-bridge.md)). Run
`qaqc_checker_list_rule_packs` once. The pyRevit bridge runs scripts, so only try
discover, and only run a script through the approval gate on a scratch model.

## E. Panel checks

Open the panel from the **AEC Bridge** tab.

1. **First-run Setup check (#60).** The Setup check card should be at the top
   and run by itself. Working looks like: "Ready" when hub, live mode, Revit
   connection, workspace and AI provider are fine; otherwise "N steps to fix"
   with a "What to do" per failing check
   ([first-check.md](first-check.md)). Break one on purpose (set mock mode) and
   confirm the card says so.
2. **Narrow width.** Dock the panel and drag it to its narrowest. Working looks
   like: no horizontal scroll, buttons and badges still readable, rail labels
   not cut off. Note the width in pixels where it breaks.
3. **Finished plans still showing live buttons (known bug).** After B, look at
   the executed plan in the panel. Known: executed, rejected or reverted plans
   may still show Approve or Reject buttons. Record what buttons show on a
   finished plan, and what happens if you press one (expected: an error, and
   no second execution).
4. **Approve Selected (known bug).** Make two or more pending plans, tick them,
   press Approve Selected. Known to misbehave. Record exactly what happens:
   which plans changed state, and any error text. Do not use it on a model you
   care about.
5. **Panel shim checks (#93).** The panel hub should refuse requests with a
   foreign Host, Origin or Content-Type. From PowerShell,
   `Invoke-RestMethod http://127.0.0.1:8787/health` should work, and
   `curl.exe -i -H "Origin: http://evil.example" http://127.0.0.1:8787/health`
   should be refused. UNVERIFIED which status code; record it. The panel itself
   must still work after this change. That is the main thing to check.

## F. Multi-Revit check

Known limit: the panel hub listens on fixed port 8787 and a second Revit
attaches to the hub the first one started, so two Revits can end up sharing one
hub ([ADR 0014](0014-multi-revit-routing.md)). This is not fixed on dev.

Only do this on scratch models. Open Revit 2024 and 2026 (any two versions) with
a different scratch model in each. Open the panel in both. Ask each panel for
the document name (for example a model summary) and note which model answers.
Working today would be each panel answering for its own Revit. The expected
result is that both answer for the same Revit. Record which, and do **not**
approve any write plan in this setup.

## G. Results table and where to report

Mark each row PASS, FAIL, or N/A, add the exact message on a failure, and
attach `bridge.jsonl` lines if it is a failure.

| Section | Check | Result | Notes (messages, ids, screenshots) |
|---|---|---|---|
| A | Build and install from dev | | |
| A | `/health` healthy | | |
| A | Tools list shows new tools | | |
| B | One write applied, no crash | | |
| B | Ctrl+Z restored the value | | |
| C | Demo steps 0 to 5 | | |
| C | Demo steps 6 to 8 | | |
| C | Rejected-plan run | | |
| D | model_bloat_audit | | |
| D | sheet_view_audit_run_audit | | |
| D | model_changes (list, compare) | | |
| D | schedule_consistency | | |
| D | naming_checker | | |
| D | warnings_triage | | |
| D | links_worksets_audit | | |
| D | clash_triage | | |
| D | bcf_exchange | | |
| D | review pack | | |
| D | rule packs, pyRevit discover | | |
| E | First-run Setup check | | |
| E | Narrow width | | |
| E | Finished plans, live buttons | | |
| E | Approve Selected | | |
| E | Panel shim Host/Origin | | |
| F | Two Revits, one hub | | |

Report results as an issue on
[Sam-AEC/aec-model-bridge](https://github.com/Sam-AEC/aec-model-bridge/issues)
titled "dev test run <date>", with the table, the dev commit, the Revit year and
the failing lines from `%APPDATA%\AECModelBridge\Logs\bridge.jsonl`. File one
issue per failure if you can, and name the PR number it came from (see "What is
on dev").
