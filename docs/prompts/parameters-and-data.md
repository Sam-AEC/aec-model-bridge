# Parameters and data prompts

Prompts for reading, checking and changing parameter data. Reads run freely. Every change is drafted as a plan; the assistant cannot approve it. How prompts map to approval: [README](README.md#how-prompts-map-to-the-approval-flow).

### PAR-01 Parameter completeness heatmap

- **When to use:** Before a data drop, to see which parameters are empty.
- **Prompt:**

```text
Measure how complete the data is in the open model. Change nothing.
Take a snapshot, then run param_completeness_heatmap with parameters {parameter_list}, categories {category_list} and by_level true.
Show filled, total and percent per category and parameter. List the five worst gaps first.
Write the CSV with csv_filename "{file}" in the workspace and tell me its path.
```

- **Tools:** `snapshot_take`, `param_completeness_heatmap`
- **Expected result:** A table of fill rates per category, parameter and level, plus a CSV in the workspace.
- **Tested:** Mock: exercised.

### PAR-02 Bulk-fill one parameter by filter

- **When to use:** Many elements need the same value, for example Fire Rating on doors on one level.
- **Prompt:**

```text
Set "{parameter}" to "{value}" on {category} elements on level "{level}".
1. Confirm the document with revit_get_context.
2. Take a snapshot and run parameter_manager_filter_params to find the elements and their current values. Show me the count and five examples. Stop if the count is zero or larger than {max_count}.
3. Prepare the change with parameter_manager_plan_set_params, then draft it with plan_actions using the exact tool arguments. Add a review text: what changes, how many elements, and any element you skipped and why.
4. You cannot approve the plan. Tell me to review it in the Revit panel and wait until I say it is approved.
5. Then run execute_plan with the plan_id.
6. Read the values back with revit_get_parameters and report what changed and what did not.
```

- **Tools:** `revit_get_context`, `snapshot_take`, `parameter_manager_filter_params`, `parameter_manager_plan_set_params`, `plan_actions`, `execute_plan`, `revit_get_parameters`
- **Expected result:** A pending plan with before-values, then, after approval, a read-back that matches the plan.
- **Safety:** The write happens only through `execute_plan` after a person approves. Without approval `execute_plan` is refused (observed in mock mode: "Plan ... is in state 'pending', not 'approved'").
- **Tested:** Mock: exercised up to the gate (filter, draft and plan ran; `execute_plan` was refused because nobody approved).

### PAR-03 Excel round trip

- **When to use:** A person or consultant prefers to edit values in Excel.
- **Prompt:**

```text
Export {parameter_list} for all {category} elements to Excel so I can edit it.
Take a snapshot and run parameter_manager_export_params_xlsx with output_filename "{file}". Tell me the path and the number of rows.
When I say the file is edited, run parameter_manager_import_params_xlsx with the same snapshot_id. Show me the row diff: element, parameter, old value, new value. Do not include unchanged rows.
The import returns a draft. Pass its actions to plan_actions and give me the plan_id. You cannot approve it; tell me to approve it in the Revit panel and wait.
After I approve, run execute_plan, take a new snapshot and confirm the change with snapshot_diff.
```

- **Tools:** `snapshot_take`, `parameter_manager_export_params_xlsx`, `parameter_manager_import_params_xlsx`, `plan_actions`, `execute_plan`, `snapshot_diff`
- **Expected result:** An .xlsx in the workspace, then a draft plan with only changed rows, then a diff after execution.
- **Safety:** The import only returns a draft; `plan_actions` registers it for approval. The values are written by `execute_plan` after a person approves.
- **Tested:** Mock: exercised (export only; import and execute were not run).

### PAR-04 Duplicate Marks and missing required values

- **When to use:** Door, window or equipment schedules show duplicates or blanks.
- **Prompt:**

```text
Check {category_list} for duplicate and missing values. Change nothing.
Run revit_check_naming_and_params with categories {category_list}, required {required_parameters} and unique {unique_parameters}.
List each duplicate value with its element ids, and each element missing a required value.
Suggest a numbering pattern for the duplicates, but do not change anything.
```

- **Tools:** `revit_check_naming_and_params`
- **Expected result:** Lists of duplicates and blanks with element ids.
- **Tested:** Mock: exercised.

### PAR-05 Add a shared parameter

- **When to use:** A client data requirement needs a parameter the project does not have yet.
- **Prompt:**

```text
I need a shared parameter "{parameter}" of type {data_type} in group {parameter_group}, bound to {category_list}.
1. Check whether it already exists with revit_list_shared_parameters and revit_list_project_parameters. If it exists, stop and tell me.
2. Otherwise draft one plan with plan_actions that calls revit_create_shared_parameter and, if needed, revit_create_project_parameter for the binding.
3. You cannot approve the plan. Tell me to approve it in the Revit panel and wait.
4. After I approve, run execute_plan and list project parameters again to confirm the binding.
```

- **Tools:** `revit_list_shared_parameters`, `revit_list_project_parameters`, `plan_actions`, `revit_create_shared_parameter`, `revit_create_project_parameter`, `execute_plan`
- **Expected result:** A plan that adds one parameter, then a read-back of the binding.
- **Safety:** Parameter creation changes the project template data and is hard to undo. It runs only after approval.
- **Tested:** Mock: exercised (the two list calls only).

### PAR-06 Door and room schedule consistency

- **When to use:** Before issuing door schedules.
- **Prompt:**

```text
Check door and room schedule data in the open model. Change nothing.
Take a snapshot and run schedule_consistency_check_doors_and_rooms with mark_pattern "{mark_regex}".
Report duplicate or missing door Marks, missing or identical From/To rooms, unnumbered or duplicate room numbers and zero-area rooms.
Say whether the check was complete.
```

- **Tools:** `snapshot_take`, `schedule_consistency_check_doors_and_rooms`
- **Expected result:** Grouped findings with element ids and a completeness flag.
- **Tested:** Mock: exercised.

### PAR-07 Undo a parameter change

- **When to use:** An approved and executed plan turned out to be wrong.
- **Prompt:**

```text
Plan {plan_id} set the wrong values. Help me undo it.
1. Read its proof bundle with get_proof_bundle and show me the before and new values per element.
2. Draft a revert plan with plan_revert. Tell me about any element that changed again since the plan ran.
3. You cannot approve the revert plan. Tell me to approve it in the Revit panel and wait.
4. After I approve, run execute_plan and read the values back with revit_get_parameters.
```

- **Tools:** `get_proof_bundle`, `plan_revert`, `execute_plan`, `revit_get_parameters`
- **Expected result:** A revert plan with the recorded before-values, approved like any other plan.
- **Safety:** The revert is a new plan and needs approval. Revert covers parameter values only; file outputs are not undone.
- **Tested:** Untested (needs an executed plan; in mock mode `plan_revert` correctly refused a plan that was never executed).

### PAR-08 Material quantities for a category

- **When to use:** Early cost checks or embodied-carbon estimates.
- **Prompt:**

```text
Give me material quantities for {category}. Change nothing.
Run revit_calculate_material_quantities for {category}. Show volume and area per material, sorted by volume.
If a schedule named "{schedule_name}" exists, read it with revit_get_schedule_data and compare the totals. Explain any difference; do not guess the cause.
```

- **Tools:** `revit_calculate_material_quantities`, `revit_get_schedule_data`
- **Expected result:** A material table and, if a schedule exists, a comparison.
- **Tested:** Mock: exercised (`revit_calculate_material_quantities` only).
