# Sheet set QA before issue

`sheet_set_qa_check` checks the sheets in a saved snapshot before a drawing issue. It is read-only: it never changes the model. The only file it writes is the optional CSV in the workspace.

It is a module tool, not a QA/QC rule pack. Rule packs test one element record at a time. These checks compare sheets with each other (duplicates, numbering sequence) and read the sheet and view placement lists, which the rule engine does not read.

## Run it

```json
{"snapshot_id": "<id>", "sheet_numbers": ["A-101", "A-102"], "csv_filename": "reports/issue-qa.csv"}
```

| Argument | Default | Meaning |
| --- | --- | --- |
| `snapshot_id` | required | Saved snapshot to check. |
| `sheet_numbers` | all sheets | The issue set. A listed number that is not in the snapshot is an error. |
| `required_fields` | Sheet Number, Sheet Name, Drawn By, Checked By, Sheet Issue Date | Fields that must be filled. `Issue Date` is accepted for `Sheet Issue Date`. |
| `number_pattern` | `[A-Za-z]{1,4}[-_. ]?\d{1,4}(?:\.\d{1,3})?[A-Za-z]?` | Regex every sheet number must fully match. Empty string turns the check off. |
| `name_pattern` | not blank, no leading or trailing spaces, not `Unnamed` | Regex every sheet name must fully match. Empty string turns the check off. |
| `series_size` | 100 | Numbers within a prefix are grouped in series of this size; gaps are reported only inside a series. |
| `csv_filename` | none | `.csv` file in the workspace, one row per sheet per finding. Cells that start with `=`, `+`, `-` or `@` are prefixed with `'`. |

## Checks

| Check | Severity | Needs |
| --- | --- | --- |
| `requested_sheet_missing` | error | `sheet_numbers` |
| `duplicate_sheet_numbers` | error | sheet records |
| `equivalent_sheet_numbers` (`A-101` and `A101`) | warning | sheet records |
| `missing_required_field` | warning | the field on at least one sheet |
| `field_not_found` | warning | reported when no sheet carries the field; the field was not checked |
| `sheets_without_views` | warning | `view_uids` per sheet or `sheet_uid` per view |
| `number_pattern_mismatch`, `name_pattern_mismatch` | warning | a pattern |
| `non_sequential_numbers` | info | sheet records |
| `unparsed_sheet_numbers` | info | sheet numbers without digits |

A sheet number is split into prefix, number and suffix: `A-101.1` is prefix `A-`, number 101, suffix `.1`. Prefixes are compared without case and trailing separators. With `series_size` 100, `A-101`, `A-104` and `A-201` report one gap (`A-102 to A-103`) and no gap between the two series. Sheets flagged `is_placeholder` are not reported as having no views.

## Data the snapshot must hold

- Top-level `sheets` (with `view_uids` and `params`) and `views` lists enable every check.
- A snapshot with only `ViewSheet` element records has no placement data. `sheets_without_views` is reported as `not_enough_data` and the status is `partial`.
- A snapshot with no sheets returns `no_sheet_data`. Nothing was checked; this is not a pass.
- A truncated, category-filtered or dirty-only snapshot gives status `partial`.

`ready_for_issue` is true only when the status is `ok` and there are no error or warning findings. Results come from saved snapshot data. Snapshots taken from a live Revit session with title block fields and placement lists are UNVERIFIED for this tool.

Use `sheet_view_audit_run_audit` for views not on any sheet and default view names.
