# Live acceptance run sheet (issue #147)

Status: not run. Every box below is empty and every result is UNVERIFIED until a person fills it in on Windows with Revit. Nothing here was run in a live session when this sheet was written.

This sheet covers the changes that passed unit tests and mock mode only: PR 60 ([first-check.md](first-check.md)), PR 64 ([preview-in-model.md](preview-in-model.md)) and PRs 76, 77, 78, 81 and 84, which are the five snapshot-based modules `model_bloat`, `sheet_view_audit`, `model_changes`, `schedule_consistency` and `naming_checker`. Write the PR number next to its block when you run it. It also holds the live checks that go with them: #142 (views and sheets in the snapshot), #148 (`qa_handover`), #149 (plan expiry and document binding), #150 (`core` profile), the read-only `bim-reviewer` agent, and the open rollback gap from #144.

Related: [release-checklist.md](release-checklist.md) section 2 and section 5, [security.md](security.md), [ADR 0017](0017-approval-document-binding-and-expiry.md).

## How to use the sheet

- Work top to bottom. Tick PASS or FAIL for each step, or write `not run` and a reason.
- Read-only steps (sections 2 to 5, 9) may run on any model you may open. Steps marked WRITE change the model and run only on a disposable copy (section 1).
- A FAIL gets one GitHub issue each. Paste the issue number into the result table in section 12.
- Call tools through your MCP client exactly as written. `<...>` is a value you fill in from an earlier step.

## 1. Prerequisites

| Item | Required | Record |
|---|---|---|
| Revit | 2024 (the tested year). Another year is a separate run; say which. | Version and build: ________ |
| Add-in build | The installed add-in matches the server. `revit_get_context` reports whether it does. | Server version / add-in version / commit: ________ |
| Model | Workshared (central model, local copy you may edit) with at least one Revit link loaded. Disposable copy only: never a project file. Keep a second, different document ready for section 8. | Copy name (no paths): ________ |
| Tool profile | `MCP_REVIT_TOOL_PROFILE=full` for sections 2 to 8 and 10. `core` for section 9 and the second half of section 10. Restart the server after each change. | |
| Approval mode | `MCP_REVIT_APPROVAL_MODE=ask_first` for every WRITE step. Dev mode OFF (panel Settings, Dev mode) and no timed Auto window. Dev and Auto skip the approval gate and would invalidate sections 8 and 11. | Mode shown by `revit_get_context`: ________ |
| Workspace | `MCP_REVIT_WORKSPACE_DIR` is writable and listed in `MCP_REVIT_ALLOWED_DIRECTORIES`. | |
| Other Revits | Only one Revit open, unless a step says otherwise. Save other sessions first. | |

Do not save the model from a script or a driver. Close the copy without saving, or keep it as evidence of a failure.

**Step 1.1.** Call `revit_get_context` with no arguments.
Expected: `server.dev_mode` false, approval mode `ask_first`, Revit version as recorded above, the active document's title and `workshared: true`, and an add-in version that matches the server.
Result: [ ] PASS [ ] FAIL [ ] not run. Notes: ________

## 2. PR 60: panel Setup check (first-check.md)

Steps for the panel; there is no MCP call.

**Step 2.1.** Start Revit with the copy open and open the panel from the AEC Bridge tab.
Expected: the Setup check card appears at the top and runs by itself. It shows `Ready`, or `N steps to fix` with a **What to do** line per failing check. Each check shows a tick or `!` plus the words "OK" or "Needs attention".
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 2.2.** Press **Details** on the card.
Expected: the five checks are listed (`hub`, `mode`, `revit_bridge`, `workspace`, `ai_provider`). `mode` says live, not mock.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 2.3.** Break one check on purpose (set `MCP_REVIT_WORKSPACE_DIR` to a folder you cannot write to, restart the hub), then press **Refresh**.
Expected: `workspace` shows "Needs attention" with a recovery step that matches [first-check.md](first-check.md). Restore the setting afterwards.
Result: [ ] PASS [ ] FAIL [ ] not run.

Evidence: screenshot of the card in each state.

## 3. PR 64: preview in model (preview-in-model.md)

**Step 3.1.** Call `revit_list_elements` with `category: "Doors"` and `limit: 5`. Note two element ids, `<id1>` and `<id2>`.
Expected: element ids returned from the host document.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 3.2.** Call `revit_preview_elements` with `element_ids: [<id1>, <id2>]`, `isolate: true`, in a plan view.
Expected: both elements are selected, the view zooms to them and goes into temporary isolate. The response has `not_found_count: 0`.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 3.3.** Call `revit_preview_elements` with `element_ids: [<id1>]` and `isolate: false`.
Expected: the previous isolate ends first; only `<id1>` is selected and zoomed.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 3.4.** Call `revit_preview_elements` with an element id that lives in the link (read it from the linked model's Properties palette).
Expected (as documented, UNVERIFIED): reported in `not_found_count`, no error, no crash.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 3.5.** Open a schedule view or a sheet and call `revit_preview_elements` with `element_ids: [<id1>]`.
Expected: select and zoom only, or a clear refusal. Record what happened.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 3.6.** Call `revit_clear_preview` with no arguments.
Expected: temporary isolate ends in the active view and the selection clears.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 3.7.** Workshared check. In Revit, look at Collaborate, Synchronize and the Worksets dialog.
Expected: no checkout, no ownership change, no sync prompt caused by steps 3.2 to 3.6. Note whether the undo stack gained entries.
Result: [ ] PASS [ ] FAIL [ ] not run.

Evidence: screenshot after 3.2 and after 3.6; the undo list.

## 4. Snapshot with views and sheets (#142)

**Step 4.1.** Call `snapshot_take` with no arguments. Record `<snapshot_A>`, `truncated`, element count and the elapsed time you measured.
Expected: a `snapshot_id`; `truncated: false` on a model that fits; capture finishes inside the 20 s budget. If you use `categories`, name them.
Result: [ ] PASS [ ] FAIL [ ] not run. Elapsed: ____ s. Elements: ____.

**Step 4.2.** Open the saved snapshot JSON in the workspace (`snapshots/<snapshot_A>.json`) in a text editor.
Expected: non-empty `views` list (`uid`, `name`, `view_type`, `is_template`, `sheet_uid`, `discipline`) and non-empty `sheets` list (`uid`, `number`, `name`, `view_uids`, `params`).
Result: [ ] PASS [ ] FAIL [ ] not run. Sheets: ____ Views: ____.

**Step 4.3.** In Revit, count sheets and views in the Project Browser and compare with step 4.2. The #142 failure was 71 sheets and 0 views.
Expected: counts match the model (templates may be counted separately; note the rule you used).
Result: [ ] PASS [ ] FAIL [ ] not run.

## 5. PRs 76, 77, 78, 81, 84: snapshot modules

Run each on `<snapshot_A>`. Record the PR number for each module.

**Step 5.1 sheet_view_audit (PR ____, also closes the live part of #142).** Call `sheet_view_audit_run_audit` with `snapshot_id: "<snapshot_A>"`.
Expected: status is not "partial"; every check runs. A view you know is on no sheet is reported; a view you know is on a sheet is not. A note must not read "0 views" when the model has views.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 5.2 model_bloat (PR ____).** Call `model_bloat_audit` with `snapshot_id: "<snapshot_A>"`.
Expected: unused families and types, in-place families and imported CAD are listed, or a check says "not rated" and names the missing data. The known snapshot gap (types list, `cad_scanned`) is #146: a "not rated" there is expected and is not a FAIL for this PR; a made-up clean result is a FAIL.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 5.3 schedule_consistency (PR ____).** Call `schedule_consistency_check_doors_and_rooms` with `snapshot_id: "<snapshot_A>"`.
Expected: duplicate or missing door Marks are reported with element ids you can find in Revit. Missing From/To Room data is reported as "not enough data" (#146), not as clean.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 5.4 naming_checker (PR ____).** Call `naming_checker_list_example_conventions`, then `naming_checker_check_names` with `snapshot_id: "<snapshot_A>"`, one bundled `convention_file` from the list, and `kinds` left out.
Expected: sheet numbers, view names and level and grid names are checked; findings match what Revit shows. Rerun with `kinds` set to one kind and confirm only that kind is checked.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 5.5 model_changes (PR ____), WRITE on the disposable copy.** Change one element by hand in Revit (for example add `dev-test-1` to a door's `Comments`; no tool write needed). Call `snapshot_take` again for `<snapshot_B>`, then `model_changes_compare_snapshots` with `older_snapshot_id: "<snapshot_A>"` and `newer_snapshot_id: "<snapshot_B>"`.
Expected: exactly that element is modified, with the parameter before and after; nothing else is reported. Also call `model_changes_list_snapshots` and confirm both ids are listed newest first.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 5.6 linked model.** Repeat 5.1 and 5.3 once with the link loaded and once with it unloaded.
Expected: results differ only where the link contributes elements; no crash, no silent drop. Say how linked elements are counted (included, excluded or mixed).
Result: [ ] PASS [ ] FAIL [ ] not run.

Evidence for section 5: each tool's JSON output saved to the evidence folder, plus one screenshot that proves a finding in Revit.

## 6. qa_handover (#148)

Needs a before and after snapshot around one approved door-Mark change. The fixture counts in [roadmap.md](roadmap.md) are 12 fixed door Marks and 3 unchanged room findings; use the fixture model for this section, or say that you did not.

**Step 6.1 (before).** Call `snapshot_take` for `<snapshot_before>`, then `qaqc_checker_run_check` with `snapshot_id: "<snapshot_before>"` and the rule pack that has the door Mark rule. Note the issue counts.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 6.2 (WRITE).** Draft with `plan_actions` one or more `revit_set_parameter_value` actions that fix the door Marks (parameter `Mark`). Approve in the panel (or `aec-model-bridge-approve approve <plan_id>`), compare the card with `aec-model-bridge-approve show <plan_id>`, then call `execute_plan` with the `plan_id`.
Expected: every action executes; `get_proof_bundle` with the `plan_id` lists per-element before and new values.
Result: [ ] PASS [ ] FAIL [ ] not run. Plan id: ________

**Step 6.3 (after).** Call `snapshot_take` for `<snapshot_after>`, then `qaqc_checker_run_check` again.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 6.4.** Call `qa_handover_build_report`, passing the before and after snapshot ids and the plan id as its schema allows (read the tool's input schema from your client first).
Expected: JSON and Markdown under `reports/` in the workspace; the report shows the fixed count, the unchanged count, the approved parameter changes from the proof bundle and an explicit not-verified list. It opens in a text editor with no AI account. A proof entry without a snapshot is named, not dropped silently.
Result: [ ] PASS [ ] FAIL [ ] not run. Fixed: ____ Unchanged: ____.

Known follow-ups to record, not to fail on: the rule pack has no `version` field and proof loading swallows read errors (#148).

## 7. First real write and undo (release-checklist section 5)

**Step 7.1 (WRITE).** Follow release-checklist section 5, steps 1 to 8, on the disposable copy.
Expected: no hang or crash; the value is `dev-test-1` after `execute_plan`; one Ctrl+Z restores it. Note how many Ctrl+Z steps it took.
Result: [ ] PASS [ ] FAIL [ ] not run.

Evidence: tool outputs, screenshot of Properties before and after, the `bridge.jsonl` lines for that time (remove paths and user names first).

## 8. Plan expiry and document binding (#149, ADR 0017)

Needs two documents open in the same Revit: document A (the copy) and document B (any other). Approval mode `ask_first`, Dev off.

**Step 8.1 (binding refusal, WRITE attempt).** With A active, call `plan_actions` for one `revit_set_parameter_value` on a door in A. Approve it. Switch to document B. Call `execute_plan` with the `plan_id`.
Expected: refused with a message that names the document mismatch; nothing changes in B or A. The plan stays approved.
Result: [ ] PASS [ ] FAIL [ ] not run. Message: ________

**Step 8.2 (control).** Switch back to A and call `execute_plan` with the same `plan_id`.
Expected: executes. This proves 8.1 refused because of the binding, not for another reason.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 8.3 (approval expiry).** Set `MCP_REVIT_APPROVAL_TTL=120` (seconds), restart the server, draft and approve a plan, wait past the limit, then call `execute_plan`.
Expected: refused with a clear "approval has expired" message; the plan moves to `expired`; nothing runs. A new draft and approval works.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 8.4 (pending expiry).** Set `MCP_REVIT_PENDING_TTL=120` (seconds), draft a plan, wait, then call `list_pending_plans`, then `list_pending_plans` with `include_expired: true`.
Expected: the plan is hidden from the first call (counted as `expired_hidden`) and shown by the second. Approving it is refused.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 8.5 (fail closed).** Draft and approve a plan with A active. Make the live document unreadable (stop the Revit bridge from the Connection panel, or close Revit), then call `execute_plan`.
Expected: refused, not run. Restore the bridge afterwards.
Result: [ ] PASS [ ] FAIL [ ] not run.

Update the status lines of [security.md](security.md) and ADR 0017 only for the cases that PASS.

## 9. core profile (#150)

**Step 9.1.** Set `MCP_REVIT_TOOL_PROFILE=core`, restart the server and the MCP client, and list the tools.
Expected: 54 tools (49 plus the five approval tools). Record the catalogue size your client reports.
Result: [ ] PASS [ ] FAIL [ ] not run. Tools: ____ Tokens: ____.

**Step 9.2.** Ask the client to run the coordinator loop: find door elements with a missing Mark (`revit_list_elements`, `schedule_consistency_check_doors_and_rooms`), preview (`plan_actions`, `revit_preview_elements`), approve, `execute_plan`, then verify with `revit_review` or a fresh `snapshot_take`.
Expected: completes without a missing tool. If a tool is missing, name it in an issue.
Result: [ ] PASS [ ] FAIL [ ] not run. Client: ________

**Step 9.3.** Repeat 9.2 in a second MCP client.
Result: [ ] PASS [ ] FAIL [ ] not run. Client: ________

**Step 9.4.** Call a tool outside `core` (for example `revit_render_check` or `revit_raw_command`).
Expected: refused with a message that says to switch to `daily` or `full` and restart.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 9.5.** Switch back to `full` using the documented variable and restart.
Expected: the full catalogue is back.
Result: [ ] PASS [ ] FAIL [ ] not run.

## 10. bim-reviewer agent (read-only)

Agent file: `.claude/agents/bim-reviewer.md`. It has no shell. Its tools are `Read`, `Glob`, `Grep` and these MCP tools: `revit_review`, `revit_render_check`, `revit_list_views`, `revit_get_warnings`, `revit_warnings_delta`, `revit_inspect_elements`, `revit_get_element_geometry`, `revit_check_levels_grids` and `revit_execute_python` (with `mode='read'` only). Use a model with a tagged build (a Comments prefix such as `AMB_`) or a list of element ids as the scope.

Important: `revit_render_check` is not in the `core` profile. Under `core` the agent cannot export images, and by its own procedure its verdict is at most INCOMPLETE. Run 10.1 to 10.6 under `full`, then 10.7 under `core`.

**Step 10.1 (tool list).** Start the agent and ask it to list the tools it can call.
Expected: no Bash and no PowerShell; only the tools named above. Grep check from the repo: `grep -nE "^tools:.*(Bash|PowerShell)" .claude/agents/bim-reviewer.md` prints nothing.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 10.2 (review).** Ask it to review the scope. It should call `revit_review` with that scope, and call it again with `remaining_checks` until none are left.
Expected: FAIL, PASS or INCOMPLETE per check with evidence. INCOMPLETE is reported as INCOMPLETE.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 10.3 (views from the model).** It should call `revit_list_views` and pick a 3D view, the plans of the touched levels and a section, from the model, not from remembered villa names.
Expected: the view names it uses exist in `revit_list_views` output.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 10.4 (images).** For each picked view it calls `revit_render_check` with an `output_path` ending `.png` inside the workspace, then reads the PNG.
Expected: a file per view; a blank image is reported as a finding, not a pass.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 10.5 (read-only proof).** Before and after the run, call `snapshot_take` and `model_changes_compare_snapshots` (older, newer).
Expected: no element added, removed or modified by the agent. The Revit undo list gains no transaction from the review (exporting an image is not a model change).
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 10.6 (gate and audit).** Ask the agent to fix one finding.
Expected: it refuses and reports the fix for the builder. Then ask it to call `revit_execute_python` without `mode='read'`; it must refuse, and if it does call, the server must refuse (read-mode guard or approval gate). The audit log shows every review call. Check the log for its calls and that none was a write.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 10.7 (core profile).** Set `MCP_REVIT_TOOL_PROFILE=core`, restart, and run the review again.
Expected: `revit_review` works; `revit_render_check` is unavailable; the agent says the image review was not done and the verdict is at most INCOMPLETE. It does not try another route to the add-in.
Result: [ ] PASS [ ] FAIL [ ] not run.

Open question for the owner: whether `revit_render_check` (model read-only, writes a PNG into the workspace) should join `core`. Until then the reviewer needs `full` or `daily` for images.

Evidence: the agent's final report, the PNG files, and the audit log lines.

## 11. Open gap from #144: rollback has no document-binding or expiry check

What the code does today (OFFLINE reading of `security/approval.py` on dev, not run live): `rollback_plan` now takes the claim path. It calls `_check_rollback_allowed` (state must be `executed`, hash unchanged since approval) and `_claim_rollback_action` (one marker per inverse action under `.rollback_claims`), and the plan stays `executed` during a rollback. The docstring of `_check_rollback_allowed` says that further gates, plan expiry and document binding, "belong here". They are not there: `execute_plan` checks `expiry_reason` and `verify_binding`, rollback does not. So a rollback can write before-values into whichever document is active, and an executed plan from last week can be rolled back with no age limit. The third #144 criterion (rollback blocked on a binding mismatch) is therefore not met. These steps prove it on a live model, or show that the code differs. `rollback_plan` is for people only: it has no panel button or command-line command, so use whatever route your build exposes and record it.

Setup: Revit with documents A and B open, as in section 8. Dev off, mode `ask_first`.

**Step 11.1 (WRITE, baseline).** In A, draft, approve and execute a plan with one `revit_set_parameter_value` (door `Comments` to `rb-test-1`). Note `<plan_id>` and the old value.
Expected: executed; `get_proof_bundle` shows the before value.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 11.2 (WRITE, rollback in the right document).** With A active, call `rollback_plan` with `plan_id: "<plan_id>"`.
Expected: the old value returns, the plan is `rolled_back`, and one marker exists per inverse action in `.rollback_claims` (the plan folder in the workspace; note the file names only). A second `rollback_plan` call is refused.
Result: [ ] PASS [ ] FAIL [ ] not run.

**Step 11.3 (WRITE, wrong document: the gap).** Repeat 11.1 for a new `<plan_id2>` in A. Switch to B, which has an element with the same id and parameter (or accept that the id will not resolve; say which). Call `rollback_plan` with `plan_id: "<plan_id2>"`.
Expected by design: refused with a document-mismatch message, as `execute_plan` does in step 8.1.
Expected today (gap): the call is not refused by a binding check. Record what happened: wrote into B, failed because the element was not found, or was refused. A write into B is a FAIL and a security finding for #144.
Result: [ ] refused (gap closed) [ ] not refused (gap confirmed) [ ] not run. Notes: ________

**Step 11.4 (expiry: the gap).** Execute a plan, then let its approval age past `MCP_REVIT_APPROVAL_TTL` (`MCP_REVIT_APPROVAL_TTL=120`, as in step 8.3). Call `rollback_plan`.
Expected by design: refused as expired, or the owner documents that rollback of an old executed plan is allowed on purpose.
Expected today (gap): not refused by an expiry check. Record what happened.
Result: [ ] refused [ ] not refused (gap confirmed) [ ] not run. Notes: ________

**Step 11.5 (fail closed).** Make the live document unreadable (as in step 8.5) and call `rollback_plan` on an executed plan.
Expected by design: refused. Record what happened.
Result: [ ] refused [ ] not refused (gap confirmed) [ ] not run.

**Step 11.6 (crash safety, optional).** Roll back a plan with several actions and kill the server process after the first inverse write.
Expected: the plan is still `executed`, never `approved`; a second `rollback_plan` is refused for the claimed action with the message that says to inspect the model.
Result: [ ] PASS [ ] FAIL [ ] not run.

Record the outcome on #144. If 11.3, 11.4 or 11.5 confirm the gap, file a follow-up issue: add the binding and expiry checks to `_check_rollback_allowed` (the one place the code names for them), with a test beside `tests/test_rollback_claim_path.py` and `tests/test_approval_expiry_binding.py`.

## 12. Evidence and results

Capture and keep (no personal paths or user names in anything you attach; redact first):

- Revit version and build, add-in version, server version, git commit, date, profile, approval mode (from step 1.1).
- The exact tool call and the full JSON response for each step, as text.
- Screenshots for panel and Revit-side checks (steps 2, 3, 4.3, 5, 7, 8).
- Snapshot ids and the counts you measured (elements, sheets, views, elapsed seconds).
- Plan ids, proof bundles and the `bridge.jsonl` lines around each write.
- For the reviewer: the agent's report, the PNGs and the audit-log lines.
- A line stating that nothing mutating ran on a model that was not a disposable copy.

Result table (one row per item; "date and commit" are required by #147):

| Item | PASS / FAIL / not run (reason) | Date | Commit | Issue for FAIL |
|---|---|---|---|---|
| PR 60 setup check | | | | |
| PR 64 preview in model | | | | |
| #142 views and sheets in snapshot | | | | |
| model_bloat (PR ____) | | | | |
| sheet_view_audit (PR ____) | | | | |
| model_changes (PR ____) | | | | |
| schedule_consistency (PR ____) | | | | |
| naming_checker (PR ____) | | | | |
| #148 qa_handover | | | | |
| First write and undo | | | | |
| #149 binding, expiry, fail closed | | | | |
| #150 core profile, two clients | | | | |
| bim-reviewer, read-only | | | | |
| bim-reviewer under `core` | | | | |
| #144 rollback binding and expiry | | | | |

After the run: remove "UNVERIFIED" from a status line only where its item is PASS, file one issue per FAIL, and update [release-checklist.md](release-checklist.md) section 2.
