# Handover prompts

Prompts for hand-over reports and asset data. Reports write files in the workspace and do not change the model. How prompts map to approval: [README](README.md#how-prompts-map-to-the-approval-flow).

### HO-01 QA hand-over report

- **When to use:** At a stage end, to hand the model over with a written QA record.
- **Prompt:**

```text
Build the QA hand-over report for the open model.
1. Use snapshot {snapshot_id}, or take one if I gave none. If a later snapshot exists after fixes, pass it as after_snapshot_id.
2. Run qa_handover_build_report with rule_pack "{rule_pack}" and plan_ids {plan_ids}.
3. Show the summary: findings per rule, before and after counts, approved parameter changes, and the not-verified list.
Tell me the paths of the JSON and Markdown files.
```

- **Tools:** `snapshot_take`, `qa_handover_build_report`
- **Expected result:** JSON and Markdown reports in the workspace with an explicit not-verified list.
- **Tested:** Mock: exercised.

### HO-02 Excel model review pack

- **When to use:** The client or BIM manager wants one Excel workbook.
- **Prompt:**

```text
Build an Excel model review workbook named "{file}.xlsx" for the open model.
Take a snapshot and run report_generator_build_review_pack with rule_pack "{rule_pack}".
Tell me the file path and list the sheets in the workbook. Do not claim findings the workbook does not contain.
```

- **Tools:** `snapshot_take`, `report_generator_build_review_pack`
- **Expected result:** One workbook with cover, findings, counts and next steps.
- **Tested:** Mock: exercised.

### HO-03 Asset data completeness for facilities management

- **When to use:** Before handing data to facilities management (COBie-style fields).
- **Prompt:**

```text
Check asset data for hand-over on {category_list}. Change nothing.
Required parameters: {parameter_list} (for example Manufacturer, Model, Serial Number, Installation Date).
1. Take a snapshot and run param_completeness_heatmap with those parameters and categories.
2. Export the elements with gaps using parameter_manager_export_params_xlsx so the contractor can fill them in.
Report fill rates and the file path. Do not fill values yourself.
```

- **Tools:** `snapshot_take`, `param_completeness_heatmap`, `parameter_manager_export_params_xlsx`
- **Expected result:** Fill rates per parameter and an Excel file of gaps. Filled values come back through the Excel round trip in [PAR-03](parameters-and-data.md#par-03-excel-round-trip).
- **Tested:** Mock: exercised (`param_completeness_heatmap` only).

### HO-04 Record of approved changes

- **When to use:** An auditor or client asks what the AI changed and who approved it.
- **Prompt:**

```text
List the model changes made through AEC Model Bridge for plans {plan_ids}. Change nothing.
For each plan run get_proof_bundle and report: approver, time, document, each element with before and new values, skipped elements and the outcome.
Run list_pending_plans and list plans still waiting for approval separately.
```

- **Tools:** `get_proof_bundle`, `list_pending_plans`
- **Expected result:** A per-plan change record taken from the proof bundles.
- **Tested:** Mock: exercised (`list_pending_plans` only; proof bundles need an executed plan).
