# Parameter Excel round-trip

Edit parameters in Excel, then turn the edits into a plan you can review.

## Steps

1. `parameter_manager_export_params_xlsx` writes an `.xlsx` workbook to the workspace.
   Give it an `element_filter`, the `param_names` you want, and an `output_filename`
   such as `doors.xlsx`. The sheet is called `Parameters`. The first columns are
   `uid`, `element_id`, `category`, `family` and `type_name`, then one column per parameter.
2. Edit parameter cells in Excel. Do not change the `uid` column.
3. `parameter_manager_import_params_xlsx` reads the workbook and compares each row
   with the snapshot. It returns a draft ActionPlan. The preview holds the changed
   cells (`before` and `after`), the blocked cells with a reason, and a `row_diff`
   count of rows, changed rows, unchanged rows and rows whose `uid` is not in the snapshot.
4. Pass the draft to `plan_actions`. A person approves it in the panel before
   `execute_plan` runs. The import tool never writes to the model.

## Rules

- File names are plain names in the workspace root and must end in `.xlsx`.
  Paths, folders and `..` are refused.
- Cells equal to the snapshot value are ignored. Blank cells are ignored; clearing
  a value is not supported.
- Read-only parameters, wrong storage types and unknown `uid` rows are blocked, as
  with the CSV import.
- Formulas are read as their last saved value.

## Not verified

Applying the approved plan in a live Revit session has not been tested.
