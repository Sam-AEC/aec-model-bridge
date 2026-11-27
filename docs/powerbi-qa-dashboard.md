# Power BI dashboard for exported QA data

This page shows how to load the QA CSV files that the bridge writes into Power BI Desktop. It ships Power Query M scripts, not a `.pbit` file. A `.pbit` is a binary package that cannot be reviewed as text. Nothing here has been opened in Power BI Desktop: the scripts and measures are UNVERIFIED until someone checks them there and records the result.

The files are read-only exports. Nothing in Power BI writes back to Revit or to the workspace. Model changes still go through `plan_actions`, human approval and `execute_plan`.

## Export the CSV files

Ask the tools to write each CSV inside the workspace folder, in a `qa` subfolder. The file names below are the ones the scripts read.

| Tool | `csv_filename` | Script |
|---|---|---|
| `sheet_set_qa_check` | `qa/sheet_set_qa.csv` | `docs/examples/powerbi/sheet-set-qa.pq` |
| `param_completeness_heatmap` | `qa/param_completeness.csv` | `docs/examples/powerbi/param-completeness.pq` |
| `model_health_score` | `qa/model_health.csv` | `docs/examples/powerbi/model-health-trend.pq` |

Export again to refresh. Each export overwrites the file of the same name.

## Load the data

1. In Power BI Desktop choose Transform data, then Manage parameters, then New parameter. Name it `WorkspaceFolder`, type Text, and set it to the workspace folder, for example `C:\Users\you\aec-workspace`.
2. For each script choose New source, Blank query, then Advanced editor. Paste the script. Name the query `SheetSetQa`, `ParamCompleteness` or `ModelHealth`.
3. Choose Close and apply.

Each script stops with a "Missing columns" error that names the absent columns when the CSV header does not match. It does not guess. A cell that the exporter prefixed with an apostrophe (to stop a spreadsheet running it as a formula) has the apostrophe removed.

## Columns

| Table | Column | Type | Meaning |
|---|---|---|---|
| `SheetSetQa` | `severity` | text | `error`, `warning` or `info`. |
| | `check` | text | Name of the check that raised the finding. |
| | `sheet_number`, `sheet_name`, `unique_id` | text | The sheet. For a numbering gap, `sheet_number` is the missing number. |
| | `detail` | text | What is wrong. |
| | `next_step` | text | Suggested action. |
| `ParamCompleteness` | `category`, `parameter` | text | One row per category and parameter. |
| | `level` | text | Present only when `by_level` was set. The script adds it as blank otherwise. |
| | `filled`, `total` | whole number | Elements with a value, and all elements. |
| | `percent` | number | `filled` as a percentage of `total`. |
| `ModelHealth` | `snapshot_id` | text | One row per saved snapshot. |
| | `taken_at` | date and time with zone | When the snapshot was taken. |
| | `score`, `delta` | number | Score from 0 to 100, and the change from the previous point. `delta` is blank when the two points are not comparable. |
| | `comparable`, `partial` | true or false | Whether the point can be compared, and whether it used a partial capture. |
| | `warnings`, `qa_findings`, `unplaced_rooms`, `unused_types`, `completeness` | number | Component sub-scores. Blank when the input was not in the snapshot. |
| | `excluded` | text | Components left out of the score, separated by `; `. |

A test (`test_powerbi_qa_template.py`) compares these column lists with the headers the exporters write, so a change to an export breaks the test before it breaks a dashboard.

## Measures

Add these in the Modeling tab. They are plain DAX and UNVERIFIED.

```dax
Open Findings = COUNTROWS ( SheetSetQa )

Errors = CALCULATE ( COUNTROWS ( SheetSetQa ), SheetSetQa[severity] = "error" )

Sheets Affected = DISTINCTCOUNT ( SheetSetQa[unique_id] )

Filled Percent = DIVIDE ( SUM ( ParamCompleteness[filled] ), SUM ( ParamCompleteness[total] ) )

Latest Score =
VAR LastTaken = MAX ( ModelHealth[taken_at] )
RETURN CALCULATE ( MAX ( ModelHealth[score] ), ModelHealth[taken_at] = LastTaken )

Latest Change =
VAR LastTaken = MAX ( ModelHealth[taken_at] )
RETURN CALCULATE ( MAX ( ModelHealth[delta] ), ModelHealth[taken_at] = LastTaken )
```

`Filled Percent` sums counts before dividing, so it is not an average of row percentages.

## Suggested visuals

- Cards: `Latest Score`, `Latest Change`, `Open Findings`, `Errors`.
- Line chart: `taken_at` on the axis, `score` as the value, from `ModelHealth`.
- Stacked bar: `check` on the axis, `Open Findings` as the value, `severity` as the legend.
- Table: `SheetSetQa` with `severity`, `sheet_number`, `sheet_name`, `detail`, `next_step`, sorted by `severity`.
- Matrix: `category` on rows, `parameter` on columns, `percent` as the value, with conditional colour. Add `level` as a slicer when it is present.

The tables are not related to each other. `SheetSetQa` and `ParamCompleteness` describe one snapshot each, so export them from the snapshot you want to review.

## Record a manual check

To close the manual-check item on issue #189, open the scripts in Power BI Desktop against CSV files exported from a saved snapshot, and note the Power BI Desktop version and the result. Until that is recorded, treat the scripts as unverified.
