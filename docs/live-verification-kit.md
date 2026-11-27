# Live verification kit

One card per open live check. Run the cards in order on a disposable copy of a model, in the Revit year each card names. The kit is read-only unless a card says WRITE. Related: [release checklist](release-checklist.md) section 2, [Revit 2024 live validation](revit-addin-live-validation-2026-10-14.md).

## Before you start

1. Open a scratch copy of a model. Never a project file. Close other Revit documents.
2. Start the panel hub. Set approval mode to `ask_first`. Dev mode and timed Auto stay off.
3. Find the Revit process id (Task Manager, Details tab).
4. Run the automated part. It makes only read calls, then writes a JSON and a Markdown report:

```powershell
cd packages\mcp-server-revit
uv run python ..\..\scripts\revit\acceptance\run.py --kit --pid <PID>          # prints the plan, no calls
uv run python ..\..\scripts\revit\acceptance\run.py --kit --pid <PID> --run    # live read calls
```

The reports go to `artifacts\revit-kit\kit-<time>-<id>.json` and `.md`. The exit code is 1 if any card is AUTO-FAIL or the Revit context is unreachable. Output is ASCII only.

## What the kit calls

Only these tools, through the authenticated panel hub: `revit_health`, `revit_get_context`, `revit_extract_snapshot` (writes one snapshot file in the workspace), `sheet_view_audit_run_audit`, `schedule_diff_compare`, `model_health_score`, `param_completeness_heatmap`, `policy_show`, `list_pending_plans`. It never calls `plan_actions`, `execute_plan`, approval tools or `revit_execute_python`. A tool outside the list is refused before it is sent.

## Report fields

- Top level: `timestamp`, `revit_version`, `addin_version`, `server_version`, `approval_mode`, `document.title_sha256_16` (a hash, never the title), `document.is_workshared`, `calls` (every tool the run called), `prerequisite_error`, `snapshot_error`.
- `cards.<issue>.status`: `AUTO-PASS`, `AUTO-FAIL` or `MANUAL`.
- `cards.<issue>.evidence`: what the automated part measured.
- `cards.<issue>.manual_remaining`: what still needs a person.

AUTO-PASS covers only the automated part. A card with text in `manual_remaining` is not done until you have done its steps and pasted the evidence in the issue. Evidence for manual steps has no report field: paste it in the issue comment, with the Revit version and commit.

## Pass and fail

Record PASS, FAIL or "not run, reason" for every card, with the date, the Revit year and the commit. A FAIL gets its own issue, linked from the card's issue. If the build does not include the change (see each card's first precondition), write "not run, not merged".

## Read-only cards

### Card 1: #142 Snapshot has view and sheet records

- Preconditions: Revit 2024 or later. A model with sheets, views placed on sheets, and at least one view on no sheet. Mode: read-only.
- Steps:
  1. Run the kit with `--run`.
  2. In an MCP client, call `revit_extract_snapshot`, then `sheet_view_audit_run_audit` with the returned `snapshot_id`.
  3. In Revit, note one view that is on no sheet and one that is on a sheet.
- Expected: the audit has no `headline` of "views not captured: result not rated". It lists the unplaced view and not the placed one. Snapshot time is 20 seconds or less.
- Evidence: `cards.142.evidence` (`audit_status`, `headline`, `views_captured`, `rated`, `snapshot_seconds`). Paste in the issue: the name of the unplaced and the placed view and whether the audit listed each; repeat on the real project.
- Pass: AUTO-PASS, and the unplaced view is listed and the placed one is not. Fail: a headline appears, `views_captured` is false, the status is `no_sheet_view_data`, or the snapshot takes more than 20 seconds.

### Card 2: #367 Snapshot holds schedule rows

- Preconditions: Revit 2024 or later. A model with a normal schedule, a key schedule and a multi-category schedule, and one schedule with more rows than the per-schedule limit. Mode: read-only.
- Steps:
  1. Run the kit with `--run`.
  2. Call `revit_extract_snapshot` twice, with one schedule row edited by hand in Revit between the calls. Call `schedule_diff_compare` with the two ids.
- Expected: `schedules.status` is `compared` or `partial`, never `not_captured`. The edited row shows as changed. The large schedule is flagged as cut short.
- Evidence: `cards.367.evidence` (`schedules_status`, `diff_status`). Paste in the issue: rows per schedule type, the truncation flag, and the snapshot file size next to the size before the change.
- Pass: AUTO-PASS, all three schedule types captured, and the size stays in the existing budget. Fail: `not_captured`, a missing schedule type, or a size over budget.

### Card 3: #371 Modal dialog reported by health

- Preconditions: Revit 2024 or later. The change is in the build (the issue is open; if `/health` has no dialog status, write "not run, not merged"). Mode: read-only.
- Steps:
  1. In Revit, open a modal dialog (Save As).
  2. Call `revit_get_context` and a read-mode `revit_execute_python`. Request the hub `/diagnostics` as in [troubleshooting](troubleshooting.md).
  3. Read `/health` and the `revit_get_result` answer for the queued request.
  4. Close the dialog.
- Expected: health and `revit_get_result` report `blocked_by_dialog` with the window title, ASCII-escaped. After closing the dialog the queued call finishes.
- Evidence: the `/health` JSON and the `revit_get_result` JSON. Kit field: none; `cards.371.status` stays MANUAL.
- Pass: both name the dialog. Fail: the call stays `running` with no reason.

### Card 4: #372 revit_reconnect after a Revit restart

- Preconditions: Revit 2024 or later, one MCP client connected. Mode: read-only.
- Steps:
  1. Call `revit_get_context`.
  2. Close and restart Revit, open the same copy.
  3. Call `revit_get_context` (it is refused by design).
  4. Call `revit_reconnect`. With two Revits open, call it again with `pid`.
  5. Call `revit_get_context`.
- Expected: step 4 lists the sessions (process id, version, document title) and binds the only live one. With several, nothing changes until `pid` is given. The result carries "Check the model before repeating an earlier write". Step 5 works without restarting the client. Pending plans are unchanged.
- Evidence: the step 3, 4 and 5 results. Kit field: none; status stays MANUAL.
- Pass: step 5 works without restarting the client and no plan changed. Fail: any silent switch to another session, or a restart needed.

### Card 5: #397 Ribbon Dev group follows Dev mode

- Preconditions: Revit 2024 or later. The change is in the build (the 1.6 ribbon has no Dev group; if it is still missing with Dev on, record FAIL for the issue as open, not a regression). Mode: read-only.
- Steps:
  1. With Dev mode off, look at the AEC Bridge ribbon tab.
  2. Switch Dev mode on in the panel (Settings, Dev mode). Look at the tab again.
  3. Switch it off. Look again.
- Expected: the Dev panel with Reports, Status, Config and Disconnect shows only while Dev is on.
- Evidence: three screenshots of the ribbon. Kit field: none; status stays MANUAL.
- Pass: the group appears and disappears with Dev mode. Fail: it is always shown, never shown, or lags behind the panel.

### Card 6: #211 revit_export_image as MCP image content

- Preconditions: Revit 2024 or later. A multimodal MCP client. The change is in the build (the issue is open; if `revit_export_image` has no image option, write "not run, not merged"). Mode: read-only (the tool writes one image file in the workspace).
- Steps:
  1. Call `revit_export_image` with a `view_id` and the new option on.
  2. Repeat with the option off.
  3. Repeat with a size that goes over the cap.
- Expected: step 1 returns one `image` content block next to the JSON text. Step 2 is unchanged from before. Step 3 is refused with a message that names the cap, not truncated.
- Evidence: the three tool results (image block present or not, message text). Kit field: none; status stays MANUAL.
- Pass: all three match. Fail: any other result.

### Card 7: #147 Workshared model with links

- Preconditions: Revit 2024 or later. A disposable copy of a workshared model with at least one linked file. Mode: read-only. Do not run anything that changes the model.
- Steps:
  1. Run the kit with `--run`.
  2. For each PR block, run the checks: PR 60 (panel setup check, [install](install.md)), PR 64 ([preview in model](preview-in-model.md)), PR 76 `model_bloat`, 77 `sheet_view_audit`, 78 `model_changes`, 81 `schedule_consistency`, 84 `naming_checker`. Use the tools named in each module's docs on the copy.
  3. Per block write: model, Revit version, exact calls, expected, measured, PASS or FAIL.
- Expected: each block finishes, or fails with a plain message. Linked elements are neither counted as host-model elements nor reported as errors.
- Evidence: `cards.147.evidence.is_workshared` (must be true), plus the per-PR sheet pasted in the issue. State in the issue that nothing mutating was run.
- Pass: every PR has PASS, FAIL or "not run, reason". Remove UNVERIFIED from a doc only for a PASS. Fail: each FAIL gets an issue.

### Card 8: #281 Named-pipe transport ACL

- Preconditions: Revit 2024 or later, Windows. `AEC_BRIDGE_TRANSPORT=pipe` set for Revit before it starts, and `MCP_REVIT_BRIDGE_TRANSPORT=pipe` for the server. Mode: read-only.
- Steps:
  1. Start Revit and open the copy. Read the registry entry for `pipe_name`.
  2. Check the pipe ACL: allowed for the current user only (PowerShell: `(Get-Acl "\\.\pipe\<pipe_name>").Access`).
  3. Call `revit_get_context` over the pipe.
  4. Start a second Revit without `AEC_BRIDGE_TRANSPORT`, so it publishes no pipe. Keep the server variable on `pipe` and call again.
  5. Try to open the pipe as another Windows user.
- Expected: only the current user has access. The context call works over the pipe. Without a pipe the client falls back to HTTP with a warning. The other user is refused.
- Evidence: the ACL output, the context result, the warning text. Kit field: none; status stays MANUAL.
- Pass: all four match; then remove the known limit from [security](security.md). Fail: any other user can open the pipe, or no warning appears on fallback.

### Card 9: #280 Live model cache from DocumentChanged

- Preconditions: Revit 2024 or later. The change is in the build (the issue is open; if no cache tool exists, write "not run, not merged"). A mid-size model. Mode: read-only for the tools; you change one element by hand in Revit.
- Steps:
  1. Take a snapshot. Note the time.
  2. Change one element by hand (a Comments value).
  3. Ask for a refresh and note the time.
  4. Do the same with a full snapshot for comparison.
  5. Switch to a second document and ask for a cached answer.
- Expected: the refresh sends only the changed element. Every cached answer states the cache age and the document. The answer for the other document is refused.
- Evidence: both times, the changed-id count, the cache age text, the refusal. Kit field: none; status stays MANUAL.
- Pass: the refresh is faster, with the age and document stated, and the cross-document read is refused. Fail: a cached answer for the wrong document.

## Mixed card

### Card 10: #218 1.6 release checks

WRITE: owner approves in the panel (the plan steps in 6 and 7 only). Steps 1 to 5 are read-only.

- Preconditions: Revit 2024 and Revit 2026, one at a time. A disposable copy of a mid-size project. The Windows bundle installed, `ids` extra included. Mode: `ask_first`.
- Steps:
  1. Install and launch (#215): start the bundled `.cmd` launchers from a path with spaces.
  2. Run `aec-model-bridge-doctor`. It must find the add-in, the token and the port. Read each failure message.
  3. Run the kit with `--run`.
  4. Call `ids_validator_validate_ifc` with a small IFC and IDS file in the workspace.
  5. Open the panel. Check the expired and bound-document labels. Call `list_pending_plans` with `include_expired` true.
  6. WRITE: owner approves in the panel. Draft a plan that touches a host element (a wall with hosted doors). Read the diff preview and the blast-radius estimate. Reject several plans at once with Reject Selected (#217).
  7. WRITE: owner approves in the panel. Set a policy file (`MCP_REVIT_POLICY_FILE`) that denies the plan's tool. Approve the plan and call `execute_plan`.
  8. In two MCP clients, list prompts and resources and use one of each. Set `MCP_REVIT_MODULE_PERMISSION_MODE=enforce` and run a module that writes outside its workspace (#216).
- Expected: launchers start. The doctor reports clearly. `model_health_score` is between 0 and 100 and the heatmap has rows. IDS returns pass or fail per specification. The preview shows the right dependents. Reject Selected rejects all selected plans. The policy denial blocks `execute_plan` and the model is unchanged. The module write outside the workspace is blocked.
- Evidence: `cards.218.evidence` (`health_score`, `heatmap_rows`, `policy_hash`, `pending_plans_listed`). Paste in the issue: doctor output, IDS result, the panel screenshots, the denial text, the client names.
- Pass: AUTO-PASS and every step matches. Fail: any step differs; open an issue per failure and link it.

## WRITE cards

Run these last. Each needs an approval in the panel. Approve only the plan you drafted for the card. Stop at the first crash or freeze and report it.

### Card 11: #150 Core tool profile in two MCP clients

WRITE: owner approves in the panel (the approval step in 3).

- Preconditions: Revit 2024 or later. Claude Desktop and one more MCP client. A model with doors missing a Mark. Mode: `ask_first`.
- Steps:
  1. Set `MCP_REVIT_TOOL_PROFILE=core` for the server in both clients and restart them.
  2. Count the tools each client lists. Call `search_tools` for one hidden tool.
  3. Run the coordinator loop: find missing Marks, preview, approve in the panel, verify.
  4. Set the variable to `full` and confirm the full list returns.
- Expected: `core` lists the core tools (the count in [configuration reference](configuration-reference.md)). The loop finishes in both clients with no missing tool.
- Evidence: tool count per client, the name of any missing tool, the loop result. Kit field: none; status stays MANUAL.
- Pass: the loop finishes in both clients. Fail: name the missing tool in a new issue.

### Card 12: #148 qa_handover on before and after snapshots

WRITE: owner approves in the panel.

- Preconditions: Revit 2024 or later. A copy of the canonical fixture model (15 doors with 12 missing Marks, 3 room findings). Mode: `ask_first`.
- Steps:
  1. Call `revit_extract_snapshot` (the before snapshot).
  2. Draft one plan that sets the 12 door Marks with `plan_actions`. Approve it in the panel. Call `execute_plan`.
  3. Call `revit_extract_snapshot` again (the after snapshot).
  4. Call `qa_handover_build_report` with `snapshot_id` (before), `after_snapshot_id` and `plan_ids`.
  5. Open `reports\qa_handover.md` in a text editor, with no AI client open.
- Expected: the report shows 12 fixed door Marks and 3 unchanged room findings. Each fix links to its plan and element id. The after state comes from the fresh snapshot.
- Evidence: the `.md` file contents. Kit field: none; status stays MANUAL.
- Pass: the counts match and the report opens as plain text. Fail: other counts or a missing plan link. Also check that an issue exists for the rule pack version field.

### Card 13: #149 Plan expiry and document binding

WRITE: owner approves in the panel.

- Preconditions: Revit 2024 or later. Two scratch documents, A and B, open in one Revit. Mode: `ask_first`.
- Steps:
  1. In document A, draft a one-action plan with `plan_actions`. Approve it. Make B the active document. Call `execute_plan`.
  2. In A, draft another plan and approve it. Wait for the expiry time. Call `execute_plan`.
  3. Draft and approve a third plan. Make `revit_get_context` unreachable (close the panel hub, or block the bridge port). Call `execute_plan`.
- Expected: step 1 is refused as a different document. Step 2 is refused with a message that names the expiry. Step 3 is refused (fails closed). The model is unchanged after all three.
- Evidence: the three refusal messages, and parameter values in A and B before and after. Kit field: none; status stays MANUAL.
- Pass: three refusals and no change. Then update the "Before any release" entries in [security](security.md) and the status line of [ADR 0017](adr/0017-approval-document-binding-and-expiry.md). Fail: any of the three runs.

### Card 14: #293 Rolled-back preview in the panel

WRITE: owner approves in the panel. Drafting rolls back inside Revit, but treat it as a write.

- Preconditions: Revit 2024 or later. A scratch copy. Mode: `ask_first`.
- Steps:
  1. Note the undo stack and two parameter values.
  2. Draft a plan of two parameter writes with `plan_actions`. Read `rollback_preview` in `aec-model-bridge-approve show <plan_id>` and in the panel.
  3. Check the undo stack and both values.
  4. Draft a plan whose second action fails. Check the model.
  5. Change one element by hand. Ask to approve the plan from step 2.
  6. Reject every plan. Do not approve any.
- Expected: the preview lists changed element ids, before and after values and warnings, in both places. Drafting leaves the model and the undo stack unchanged. The failing preview leaves the model unchanged. After the manual change the plan needs a new preview. The preview does not count as approval.
- Evidence: the `show` output, the panel screenshot, the values before and after. Kit field: none; status stays MANUAL.
- Pass: all five match. Fail: any change in the model or the undo stack from drafting.
