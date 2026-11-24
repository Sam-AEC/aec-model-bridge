# Sheets and documentation prompts

Prompts for sheet sets, revisions and issue. Audits are read-only. Creating, renaming or exporting sheets goes through a plan that a person approves. How prompts map to approval: [README](README.md#how-prompts-map-to-the-approval-flow).

### SH-01 Pre-issue sheet audit

- **When to use:** Before any drawing issue.
- **Prompt:**

```text
Check the sheet set before issue. Change nothing.
1. Take a snapshot that includes sheets and views, then run sheet_view_audit_run_audit with required_sheet_parameters {required_parameters}.
2. Run revit_sheet_index with only_findings true.
Report empty sheets, unplaced views, duplicate sheet numbers, missing sheet parameters, default view names and sheets without the current revision.
If the audit says it had no sheet data, say so and do not report "no problems".
```

- **Tools:** `snapshot_take`, `sheet_view_audit_run_audit`, `revit_sheet_index`
- **Expected result:** A findings list per sheet, or a clear statement that no sheet data was captured.
- **Tested:** Mock: exercised (the mock snapshot has no sheets, so the audit correctly reported that nothing was checked).

### SH-02 Sheet and view naming check

- **When to use:** The project has a naming standard (for example an ISO 19650 national annex or an office standard).
- **Prompt:**

```text
Check sheet numbers, sheet names and view names against our naming convention. Change nothing.
Convention: {convention_description_or_file}.
If I gave no convention, list the bundled examples with naming_checker_list_example_conventions and ask me which to use; say that they are examples, not a standard.
Run naming_checker_check_names with that convention on a fresh snapshot. List each failing name, the field that failed and the allowed values.
```

- **Tools:** `naming_checker_list_example_conventions`, `snapshot_take`, `naming_checker_check_names`
- **Expected result:** Failing names with the reason for each.
- **Tested:** Mock: exercised (`naming_checker_list_example_conventions` only).

### SH-03 Create sheets from a CSV

- **When to use:** A sheet list exists in a spreadsheet.
- **Prompt:**

```text
Create sheets from "{file}" in the workspace, with title block "{titleblock_name}".
1. List title blocks with revit_list_titleblocks and confirm the name exists. List existing sheets with revit_list_sheets and tell me which CSV rows clash with existing numbers.
2. Draft one plan with plan_actions that calls revit_batch_create_sheets_from_csv. Put the number of sheets and any skipped rows in the review text.
3. You cannot approve the plan. Tell me to approve it in the Revit panel and wait.
4. After I approve, run execute_plan and confirm with revit_sheet_index.
```

- **Tools:** `revit_list_titleblocks`, `revit_list_sheets`, `plan_actions`, `revit_batch_create_sheets_from_csv`, `execute_plan`, `revit_sheet_index`
- **Expected result:** A plan listing the new sheets, then the updated sheet index.
- **Safety:** Sheets are created only after approval. Number clashes are reported before the plan, not resolved by guessing.
- **Tested:** Mock: exercised (`revit_list_titleblocks` only).

### SH-04 Renumber and rename sheets from a table

- **When to use:** A sheet numbering scheme changed.
- **Prompt:**

```text
Renumber and rename sheets using this table (current number, new number, new name):
{table}
1. Read the current sheets with revit_sheet_index. Flag rows whose current number does not exist and new numbers that would clash.
2. Draft a plan with plan_actions that calls revit_update_sheets with the rows that passed. Use on_error "abort".
3. You cannot approve the plan. Tell me to approve it in the Revit panel and wait.
4. After I approve, run execute_plan and show the sheet index again.
```

- **Tools:** `revit_sheet_index`, `plan_actions`, `revit_update_sheets`, `execute_plan`
- **Expected result:** A plan with only valid rows; a sheet index that matches the table after execution.
- **Safety:** `revit_update_sheets` is refused without an approved plan, also with `dry_run` (observed in mock mode).
- **Tested:** Mock: exercised (read step ran; `revit_update_sheets` was refused without a plan as expected).

### SH-05 Place unplaced views on a sheet

- **When to use:** Views exist but are not on sheets.
- **Prompt:**

```text
Find views that are not on any sheet and place the ones named like "{name_filter}" on sheet "{sheet_number}".
1. Run revit_list_views_sheets_schedules with kinds ["views"], only_unplaced true and name_contains "{name_filter}".
2. Draft a plan with plan_actions that calls revit_place_views with layout "{grid_row_or_column}" and margin_mm {margin_mm}.
3. You cannot approve the plan. Tell me to approve it in the Revit panel and wait.
4. After I approve, run execute_plan and check the sheet with revit_sheet_index.
```

- **Tools:** `revit_list_views_sheets_schedules`, `plan_actions`, `revit_place_views`, `execute_plan`, `revit_sheet_index`
- **Expected result:** Views placed as viewports inside the title block area.
- **Safety:** Placement happens only after approval.
- **Tested:** Mock: exercised (the list step only).

### SH-06 Add and issue a revision

- **When to use:** Preparing a formal issue.
- **Prompt:**

```text
Add revision "{description}" dated {date}, issued by {issued_by} to {issued_to}, and put it on sheets {sheet_numbers}.
1. List revisions with revit_list_revisions and tell me the next number.
2. Draft one plan with plan_actions: revit_add_revision, then revit_issue_revision for those sheets. Do not mark it issued unless I said "mark issued".
3. You cannot approve the plan. Tell me to approve it in the Revit panel and wait.
4. After I approve, run execute_plan and confirm with revit_list_revisions and revit_sheet_index.
```

- **Tools:** `revit_list_revisions`, `plan_actions`, `revit_add_revision`, `revit_issue_revision`, `execute_plan`, `revit_sheet_index`
- **Expected result:** A new revision on the listed sheets, shown in the sheet index.
- **Safety:** Marking a revision issued locks it in Revit. The prompt keeps that step opt-in.
- **Tested:** Mock: exercised (`revit_list_revisions` only).

### SH-07 Fill title block parameters

- **When to use:** Title blocks are missing drawn-by, checked-by or status values.
- **Prompt:**

```text
Fill title block values on sheets {sheet_numbers}: {parameter_value_pairs}.
1. Read each sheet with revit_get_sheet_info and show the current values.
2. Draft one plan with plan_actions that calls revit_populate_titleblock once per sheet. Skip sheets where the value is already correct.
3. You cannot approve the plan. Tell me to approve it in the Revit panel and wait.
4. After I approve, run execute_plan and read the sheets back.
```

- **Tools:** `revit_get_sheet_info`, `plan_actions`, `revit_populate_titleblock`, `execute_plan`
- **Expected result:** A plan with one action per sheet that needs a change.
- **Safety:** Values are written only after approval.
- **Tested:** Untested.

### SH-08 Export a sheet set to PDF

- **When to use:** Issuing PDFs.
- **Prompt:**

```text
Export sheets {sheet_numbers} to PDF as one combined file "{file}" in the workspace.
1. Confirm the sheets exist with revit_sheet_index.
2. Draft a plan with plan_actions that calls revit_export with format "pdf", the sheets, combine true and overwrite false.
3. You cannot approve the plan. Tell me to approve it in the Revit panel and wait.
4. After I approve, run execute_plan and report the file path and size from the result.
```

- **Tools:** `revit_sheet_index`, `plan_actions`, `revit_export`, `execute_plan`
- **Expected result:** A PDF in the workspace; the result names the real file and its size.
- **Safety:** The export does not change the model but writes a file, and no approval path undoes a file. Existing names are refused unless overwrite is set.
- **Tested:** Untested.
