# Coordination and clash prompts

Prompts for clash checks and coordination issues. Checks are read-only. Moving or resizing elements to fix a clash is a separate plan. How prompts map to approval: [README](README.md#how-prompts-map-to-the-approval-flow).

### CO-01 Quick category clash check

- **When to use:** A fast first pass between two disciplines inside one model.
- **Prompt:**

```text
Check clashes between {category_a} and {category_b} in the open model. Change nothing.
Run revit_check_clashes with category1 "{category_a}", category2 "{category_b}", tolerance {tolerance_feet} (feet) and max_pairs {max_pairs}.
Group the clashes by level and by element type. Show the ten largest groups with element ids.
Say that this check uses bounding boxes if the result says so.
```

- **Tools:** `revit_check_clashes`, `revit_preview_elements`
- **Expected result:** A grouped list of clash pairs.
- **Tested:** Mock: exercised.

### CO-02 Measured solid overlaps

- **When to use:** You need real overlap volumes, not bounding-box hits.
- **Prompt:**

```text
Measure solid overlaps between set A ({set_a}) and set B ({set_b}). Change nothing.
Run revit_check_intersections with min_volume_m3 {min_volume} and skip_hosted true.
Sort pairs by overlap volume. For the top ten, show both element ids, categories, levels and the location.
Offer to show the first pair with revit_preview_elements.
```

- **Tools:** `revit_check_intersections`, `revit_preview_elements`
- **Expected result:** Overlap pairs with volume in m3, largest first.
- **Tested:** Mock: exercised.

### CO-03 Navisworks clash results to Revit elements

- **When to use:** Clash Detective found clashes and you want them matched to Revit elements.
- **Prompt:**

```text
Take the results of Navisworks clash test "{clash_test_name}" and match them to elements in the open Revit model.
1. List tests with navisworks_list_clash_tests and find the Guid of "{clash_test_name}". Read its results with navisworks_get_clash_results.
2. Take a Revit snapshot and run clash_triage_match_clashes with those results and record_issues true.
3. Report how many matched exactly, how many were ambiguous and how many did not match. List the ambiguous ones with both candidates.
Do not rerun the clash test unless I ask; that writes to the Navisworks file.
```

- **Tools:** `navisworks_list_clash_tests`, `navisworks_get_clash_results`, `snapshot_take`, `clash_triage_match_clashes`, `clash_triage_list_clash_issues`
- **Expected result:** Clash issues recorded with match confidence.
- **Safety:** `navisworks_run_clash_test` changes the Navisworks document and needs an approved plan; the prompt does not call it.
- **Tested:** Untested (needs Navisworks).

### CO-04 MEP systems with open ends

- **When to use:** Before MEP coordination, to find disconnected pipework or ductwork.
- **Prompt:**

```text
Check MEP system "{system_name}" for open ends and connection problems. Change nothing.
Run revit_system_report with system "{system_name}" (or categories {category_list}).
List open connectors, elements in no system, domain mismatches and size changes without a fitting, each with element ids.
Do not claim any engineering sizing result.
```

- **Tools:** `revit_system_report`, `revit_mep_check_elements`
- **Expected result:** A list of connection findings by element.
- **Tested:** Mock: exercised (`revit_system_report` only).

### CO-05 Wall joins and openings

- **When to use:** After walls or doors were moved, or when openings do not cut.
- **Prompt:**

```text
Check wall joins and door and window openings on level "{level}". Change nothing.
1. Run revit_check_joins for walls on that level. List wall ends that are not joined.
2. Run revit_audit_openings for doors and windows on that level. List openings with no host, a wrong host or no cut in the wall.
Show element ids for each finding and say which evidence (ray or volume) the audit used.
```

- **Tools:** `revit_check_joins`, `revit_audit_openings`
- **Expected result:** Unjoined wall ends and opening problems with evidence.
- **Tested:** Mock: exercised.
