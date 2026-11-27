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

## Saved column mappings

A mapping gives the parameter columns your own headers, for example a client template.
Save it as `excel_mappings/<name>.json` in the workspace:

```json
{"columns": {"Door number": "Mark", "Fire rating": "FireRating"}}
```

Pass `mapping="<name>"` to the export instead of `param_names`, and the same name to the
import. The export writes your headers; the import maps them back and ignores columns
that are not in the mapping. A mapping that names a parameter not in the snapshot, uses a
reserved header (`uid`, `element_id`, `category`, `family`, `type_name`) or maps two headers
to one parameter is refused. Mapping names are plain names; paths are refused.

## Three-column CSV

`parameter_manager_import_params_csv` also reads a plain CSV with the columns `element_id`,
`parameter` and `value`, one row per change, for example a Google Sheets export:

```csv
element_id,parameter,value
300,Mark,D-999
200,Unconnected Height,5.5
```

`element_id` is the Revit element id from the snapshot. The result is a draft ActionPlan with
the same `before` and `after` cells and a `row_diff` (distinct elements, changed, unchanged,
unknown, and `csv_rows`). Unknown element ids, unknown or read-only parameters, blank values,
wrong storage types and a parameter given twice with different values are listed in `blocked`
and produce no action. A file that is empty, has no data rows, is over 5 MB or 50,000 rows, or
lacks one of the three columns is refused. A CSV with a `uid` column keeps the wide layout
(one column per parameter). Nothing is written until the plan is approved.

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
