# Clash triage (read-only)

First slice of the Navisworks to Revit loop scoped in ADR 0015. It answers one question for a BIM coordinator: "for each clash in my Navisworks test, which Revit elements are involved, and how sure are we?"

It never changes the Revit model and it proposes no fixes.

## How to use it

1. Run a clash test in Navisworks and fetch the results with `navisworks_get_clash_results`.
2. Capture a Revit snapshot and note its `snapshot_id`.
3. Call `clash_triage_match_clashes` with the clash results and the `snapshot_id`.
4. Read the answer per clash. Later, `clash_triage_list_clash_issues` lists what was recorded.

In mock mode (`MCP_REVIT_MODE=mock`) the snapshot is optional and generated sample data is used. When connected to Revit a real `snapshot_id` is required; the tool refuses to guess.

## What the confidence labels mean

| Label | Meaning |
| --- | --- |
| exact | The clash item's GUID matches exactly one Revit element, by its UniqueId or by its IFC GUID parameter. |
| ambiguous | The GUID matches more than one element. None is picked for you. |
| unmatched | No GUID was supplied, or no element in the snapshot has it (the model may have changed since the test). |

A clash is only "exact" when both of its items are exact. Otherwise it takes the weaker of the two labels.

## What it will not do

- It does not use the Revit ElementId or the Navisworks InstanceGuid to find elements. Those are not reliable across tools.
- It does not match by name or category, and it does not fall back to a guess.
- It does not write to the Revit model. Results are saved as issues in the workspace file `clash_triage.db`. This is kept apart from the QA/QC issue store so a QA/QC re-run cannot close clash issues by accident.

## UNVERIFIED

Everything above was tested with fixture data only. Not yet checked on a real project with Revit and Navisworks:

- What Navisworks puts in the GUID field for items that came from Revit, IFC or NWC sources.
- Whether the Revit snapshot carries an IFC GUID parameter (the module looks for a parameter named `IfcGUID`) in your models.
- How many clashes map to the right element on both sides. A person should check a sample on one real project.
- Clashes inside linked models or groups.
