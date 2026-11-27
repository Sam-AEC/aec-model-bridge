# QA handover report

A short QA and change report you can hand to a coordinator or client. It opens as plain Markdown or JSON, so reading it needs no AI account.

## Run it

Ask for `qa_handover_build_report`. Inputs:

- `snapshot_id`: the saved snapshot to report on. Required when connected to Revit. Without it, and only in mock mode, the report uses generated sample data and says so.
- `after_snapshot_id` (optional): a later snapshot of the same model. The rules run again on it and changed values are checked against it.
- `plan_ids` (optional, up to 20): plans whose proof bundles (`proofs/<plan_id>.json`) are listed as approved changes.
- `rule_pack` (default `core`), `max_ids` (element ids per rule, 1 to 30, default 10), `output_name` (default `qa_handover`).

It writes `reports/<output_name>.json` and `reports/<output_name>.md` in the workspace and returns only a one-line summary and the two file paths. It changes nothing in the model and needs no plan.

## What the report holds

- Document title and id, snapshot id, time and app version.
- Rule pack name, origin and file SHA-256 (packs have no version field).
- Findings grouped per rule: severity, element count, the first N UniqueIds, next step.
- With complete snapshots of the same identified model in chronological order: findings before and after per rule, and added, removed and modified element counts. Partial captures (truncated, dirty-only, or category-filtered) cannot establish whole-model changes or resolved findings.
- Movement and rotation coverage are explicit. When location components are missing, total modified/unchanged counts are unknown; observed changes in captured fields remain available separately.
- Per plan: outcome, who approved and when, each recorded parameter change with before and new value, skipped or failed count, and whether the after snapshot shows the new value (confirmed, differs, not checked). Bulk, script and other action outcomes are listed with their tools and errors. Their unrecorded parameter changes remain unknown, rather than counting as zero changes.
- A "Not verified" list.

## What it proves

Only what the saved files show. A value is "confirmed" when the proof and both snapshots have matching document ids, valid timestamps establish that the after snapshot was taken after the plan ran, and it holds the new value for that element and parameter. A partial capture can confirm values it actually contains; omitted values stay unknown.

A finding is "resolved" when its rule and element UniqueId appear before and no longer appear after a successful re-check on complete snapshots. New findings are counted separately, so new issues do not hide resolved issues. Failed rules or findings without complete UniqueIds have unknown resolution counts; JSON uses `null` and Markdown says `unknown`.

## What it does not prove

- Nothing is read from the live model. The approver is the OS account recorded in the proof, not an authenticated identity.
- Without an after snapshot, nothing is re-checked. An after snapshot taken before the plan ran, missing timestamps, or unmatched document identities confirm no plan values.
- A partial snapshot, a missing document id, a plan for another document, a missing proof bundle, a rule that could not run, and values that differ (or use another unit) are listed under "Not verified".
- Lists and text are capped (field length, ids per rule, 25 parameter changes and 25 other actions per plan). Known counts include records beyond those caps; unprovable totals use `null`/`unknown`. A report over 512 KB is refused, never cut silently.

## Parameter completeness heatmap

`param_completeness_heatmap` reads a saved snapshot and returns, for each category and parameter, how many elements have a value: `filled`, `total` and `percent`. Pick parameters with `parameters`, or take the `top_n` most common per category (default 8). `by_level` splits each rate per level (level names come from level elements in the snapshot). `csv_filename` and `html_filename` write a CSV and a self-contained HTML heatmap inside the workspace.

- `total` is every element of that category (on that level) in the snapshot. A blank or missing value counts as not filled; `0` and `false` count as filled. An element that lacks a parameter altogether is not filled, so the rate is "of all elements of the category".
- A truncated, dirty-only or category-filtered snapshot is labelled partial in the result, in `coverage`, and as a banner in the HTML. Its rates describe the captured elements only.
- The result lists at most `max_rows` rows; the files hold every row. It never changes the model. Without `snapshot_id` it refuses when connected to Revit; in mock mode it uses generated sample data and says so.

## LOIN completeness report

`param_completeness_loin_report` checks a saved snapshot against a level of information need (ISO 19650) requirement file. Put a `.yaml`, `.yml` or `.json` file in the workspace `loin` folder and pass its name without extension as `requirements`. Use `stage` to report one stage; without it every stage in the file is reported.

```yaml
requirements:
  - category: OST_Doors
    stage: S3
    parameters: [Mark, FireRating]
```

- Each category and stage gets `percent` (filled values over the captured parameters), `captured_parameters`, `not_captured_parameters` and one row per parameter with `filled`, `empty` and `total`.
- `not_captured` means no captured element of the category carries the parameter, or the snapshot's parameter or category filter left it out. The value is unknown. It is not counted as empty, and the category status is never `complete` while a parameter is not captured.
- A category absent from the snapshot is `not_captured` with `total` 0.
- Filled follows the heatmap rule: blank text and null are empty; `0` and `false` are values. A partial snapshot is labelled `partial`.
- Read-only. It writes no file and refuses names with folders or extensions.

## Model health score and trend

`model_health_score` gives a score from 0 to 100 (higher is better) for one snapshot and a trend across all saved snapshots with the same `source.doc_guid`, oldest first by `taken_at`, with the change from the previous point. It is a rough indicator, not a measure of file size or speed.

Score = sum(weight x subscore) / sum(weight), over the components the snapshot can support:

| Component | Weight | Subscore (0 to 100) | Needs |
| --- | --- | --- | --- |
| `warnings` | 25 | 100 - 5 x warnings per 1000 elements, minimum 0 | `counts.warnings` in the snapshot |
| `qa_findings` | 25 | 100 x (1 - elements hit by an error or warning rule / elements) | a `rule_pack` argument |
| `unplaced_rooms` | 20 | 100 x (1 - unplaced rooms / rooms) | room elements |
| `unused_types` | 15 | 100 x (1 - unused non-system types / non-system types) | a type list, matching instances, a complete capture |
| `completeness` | 15 | filled / total over the 5 most common parameters per category | elements with parameters |

An input the snapshot does not have is left out and listed under `excluded` with the reason; it is never scored as 0 or 100. No usable input means no score. A change (`delta`) is given only when both points are complete captures that used the same components; otherwise it is `null` with a `delta_note`. Today the add-in does not write `counts.warnings`, so that component is normally excluded. `csv_filename` writes the trend as CSV in the workspace.

## Model health dashboard

`model_health_score` with `html_filename` (a `.html` name inside the workspace) also writes one self-contained HTML page: inline CSS and SVG, no scripts, fonts or external links. All model text is HTML-escaped. The page holds:

- the score and its components, and the excluded inputs with reasons;
- the trend across saved snapshots of the same document as a line chart and a table (partial captures are hollow points);
- the top 10 rules by open issues from the latest stored QA/QC run of the document (`qaqc_checker_run_check`). The issue store is opened read-only. With no stored run, an unreadable store or no `source.doc_guid`, the page says so instead of showing "no issues". A run on a different snapshot than the scored one is flagged;
- parameter completeness: the 5 most common parameters per category, up to 400 rows.

The result's `dashboard` key gives the QA status and row counts; `html_file` is the written path. Mock and partial snapshots get a banner. For sheet checks before an issue see [sheet-set-qa.md](sheet-set-qa.md).

## Quantity take-off (CSV and BC3)

`qto_export_run` reads a saved snapshot and returns, per category and type, the element `count` and the summed length, area and volume in m, m2 and m3. `csv_filename` writes a CSV and a second file `<name>_no_quantity.csv`. `bc3_filename` writes a FIEBDC-3 file in ANSI (cp1252) with one chapter per category and one concept per type. It carries no prices.

- Length, Area and Volume come from the element parameters of that name. Set `snapshot_units` to `feet` (default) or `metres` to match the snapshot.
- A total is empty when no element of that type has the quantity. It is never written as 0. `*_elements` gives how many elements contributed.
- An element with none of the three quantities is counted, listed under `without_quantity` and written to the `_no_quantity` file.
- In BC3 each type has one measurement. `bc3_measure` picks it; `auto` uses area for walls, floors, roofs, ceilings and rooms, length for linear MEP and framing, volume for columns and foundations, and count (unit `ud`) otherwise. A type without that quantity falls back to count.
- IFC files are not read. Output files stay inside the workspace. It never changes the model. BC3 import in a cost tool is UNVERIFIED; the tests check the file with a minimal reader.
