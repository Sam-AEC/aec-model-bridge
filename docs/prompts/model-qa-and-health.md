# Model QA and health prompts

Read-only prompts for checking model quality. None of them changes the model. Where a prompt suggests fixes, the fixes go into a separate plan (see [parameters and data](parameters-and-data.md)). How prompts map to approval: [README](README.md#how-prompts-map-to-the-approval-flow).

### QA-01 First look at an unfamiliar model

- **When to use:** You receive a model from another team or open a project for the first time.
- **Prompt:**

```text
Give me a first look at the open Revit model. Change nothing.
1. Confirm which document is open with revit_get_context and revit_get_document_info. Stop and tell me if it is not {model_name}.
2. Take a snapshot with snapshot_take and summarise it with model_inspector_summarize_model: element counts by category, families, levels.
3. Report the five things a BIM coordinator should look at first, each with a count and the tool you used.
Say which numbers come from a partial snapshot.
```

- **Tools:** `revit_get_context`, `revit_health`, `revit_get_document_info`, `snapshot_take`, `model_inspector_summarize_model`
- **Expected result:** Document name, counts by category and a short ranked list of follow-ups.
- **Tested:** Mock: exercised.

### QA-02 Warnings triage

- **When to use:** The model has many warnings and you need to know which ones matter.
- **Prompt:**

```text
Triage the Revit warnings in the open model. Change nothing.
Take a snapshot, then run warnings_triage_review_warnings with coordinator_only true and top {top_n}.
Group the warnings by type, rank them by the number of elements they touch, and flag duplicate marks, overlapping elements and rooms not enclosed.
For the top three groups, show up to five element ids each and offer to show them with revit_preview_elements.
Do not propose fixes yet.
```

- **Tools:** `snapshot_take`, `warnings_triage_review_warnings`, `revit_get_warnings`, `revit_preview_elements`
- **Expected result:** A ranked table of warning groups with counts, element ids and a suggested next step per group.
- **Tested:** Mock: exercised (the mock snapshot has no warnings, so the groups are empty).

### QA-03 Rule-pack QA run

- **When to use:** Before a milestone, to check the model against your office rules.
- **Prompt:**

```text
Run QA/QC on the open model with the rule pack "{rule_pack}". Change nothing.
1. List the available packs with qaqc_checker_list_rule_packs and confirm "{rule_pack}" is valid.
2. Take a snapshot and run qaqc_checker_run_check with that snapshot_id and rule pack.
3. List the issues with qaqc_checker_list_issues. Report counts by rule and severity, and the ten most serious issues with element ids.
4. Say which rules did not run or had no data.
```

- **Tools:** `qaqc_checker_list_rule_packs`, `snapshot_take`, `qaqc_checker_run_check`, `qaqc_checker_list_issues`
- **Expected result:** Findings by rule and severity, recorded as issues that later prompts (BCF export, hand-over) can use.
- **Tested:** Mock: exercised.

### QA-04 Health score and trend

- **When to use:** Weekly reporting to a BIM manager.
- **Prompt:**

```text
Give me the health score of the open model and its trend. Change nothing.
Take a snapshot, then run model_health_score with include_trend true and rule_pack "{rule_pack}".
Show the score, each component of it, and the change since the previous snapshot of the same document.
Explain in one sentence per component what would raise it. Do not invent a target score.
```

- **Tools:** `snapshot_take`, `model_health_score`
- **Expected result:** A 0 to 100 score with components and a trend line if earlier snapshots exist.
- **Tested:** Mock: exercised.

### QA-05 Model bloat and purge candidates

- **When to use:** The file is slow or large and you want to know why before purging.
- **Prompt:**

```text
Find what makes the open model heavy. Change nothing.
1. Take a snapshot and run model_bloat_audit with that snapshot_id.
2. Run revit_cleanup_audit with max_ids {max_ids}.
List unused families and types, in-place families, imported CAD and the other cleanup findings, sorted by likely impact.
For each finding say whether it is safe to remove or needs a person to check. Do not delete anything; if I ask for removal later, draft a plan.
```

- **Tools:** `snapshot_take`, `model_bloat_audit`, `revit_cleanup_audit`
- **Expected result:** A ranked cleanup list with counts and element ids. No deletions.
- **Safety:** Any removal that follows must be a separate plan with `plan_actions` (for example `revit_delete_element` actions) that a person approves.
- **Tested:** Mock: exercised.

### QA-06 Links and worksets audit

- **When to use:** Workshared projects, before a coordination round.
- **Prompt:**

```text
Check linked models and worksets in the open model. Change nothing.
Read links with revit_get_rvt_links and worksets with revit_get_worksets, take a snapshot, then run links_worksets_audit_audit.
Expect shared coordinates: {yes_or_no}. Workset rules by category: {category_workset_map_or_none}.
Report unloaded or unpinned links, links not placed by shared coordinates, empty or default-named worksets, worksets owned by others, and elements on the wrong workset.
```

- **Tools:** `revit_get_rvt_links`, `revit_get_worksets`, `snapshot_take`, `links_worksets_audit_audit`
- **Expected result:** A list of link and workset findings with severity.
- **Tested:** Mock: exercised (mock data has no links or worksets, so no findings).

### QA-07 Levels and grids check

- **When to use:** Early in a project, or after levels were copied from a link.
- **Prompt:**

```text
Check levels and grids in the open model. Change nothing.
Run revit_check_levels_grids with tolerance_mm {tolerance_mm} and require_ceiling_plan {true_or_false}.
List levels without plan views, duplicate elevations and coincident grids. List all levels with name and elevation in mm.
```

- **Tools:** `revit_check_levels_grids`, `revit_list_levels`
- **Expected result:** FAIL and PASS lines for each check, plus the level table.
- **Tested:** Mock: exercised (`revit_check_levels_grids` only).

### QA-08 What changed since last week

- **When to use:** Weekly coordination, or after another team issued a new model.
- **Prompt:**

```text
Tell me what changed in the open model since the last snapshot. Change nothing.
1. List snapshots with model_changes_list_snapshots. If there is no earlier snapshot of this document, take one now and stop.
2. Take a new snapshot and compare it with the previous one using model_changes_compare_snapshots.
3. If I gave you a warnings baseline_id from the last check, run revit_warnings_delta with it. If not, run revit_warnings_delta without one: say that new warnings cannot be compared this time, and give me the baseline_id it returns for next time.
Report elements added, removed and modified per category, notable parameter changes, and new warnings.
```

- **Tools:** `model_changes_list_snapshots`, `snapshot_take`, `model_changes_compare_snapshots`, `revit_warnings_delta`
- **Expected result:** A change summary by category and a warnings delta.
- **Tested:** Mock: exercised (list and warnings delta; the compare step needs two snapshots of one document).
