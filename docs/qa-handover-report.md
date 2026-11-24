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
