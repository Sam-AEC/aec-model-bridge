# ADR 0015: Navisworks clash to Revit fix loop, and BCF

## Status
Proposed. Scoping only. No code is written for this loop. Nothing here has been run against a real Navisworks or Revit session, so every claim about how those programs behave is marked UNVERIFIED. It needs a decision from the maintainer before any work starts.

## Context
A coordinator's week often looks like this: run clash tests in Navisworks, read a long list of clashes, open each one in Revit, decide who moves what, fix it, and tell the other discipline. This record scopes how the assistant could shorten that loop without skipping the human decision:

Navisworks clash report -> issue -> proposed Revit fix -> approval gate -> change in Revit.

BCF (BIM Collaboration Format) is the usual way to pass those issues between tools, so import and export of BCF is part of the same scope.

The approval gate (ADR 0008) stays in charge. The assistant may propose a fix. It may not apply one without an approved plan.

## What exists in the repo today
Read from the code, not run.

- **Navisworks add-in (read side).** `packages/navisworks-bridge-addin/src/ClashCommands.cs` has three commands: `navis.list_clash_tests`, `navis.run_clash_test` (marked mutating) and `navis.get_clash_results` (read-only, paged with `skip` and `limit`). For each clash it returns the clash name, GUID, status, distance and centre point, plus an identity block for each of the two items: display name, class name, `InstanceGuid`, and a value read from a property named `Guid` in the `Item` category (it calls this `ifcGuid`).
- **Navisworks provider.** `providers/navisworks.py` exposes those as `navisworks_list_clash_tests`, `navisworks_run_clash_test` and `navisworks_get_clash_results`. Without a bridge it returns mock payloads. The README lists Navisworks as "in progress".
- **No export reader.** Nothing in the repo parses a Navisworks XML or HTML clash report, and nothing reads or writes a BCF zip. A search for `bcf` finds only the cloud provider (next point).
- **A BCF-shaped issue tool, not BCF files.** `providers/cloud.py` has `autodesk_data_create_topic` (alias `autodesk_data_create_issue`). It validates a `BCFTopicPayload` (title, description, status, type, `ifc_guid_refs`, viewpoint) and POSTs it to a configured `issues_endpoint`. It does not build a BCF zip, and it needs that endpoint to exist. Whether any real service accepts this body is not established here.
- **A recipe that does not do what its name says.** `recipes/export_clash_import.yaml` is titled "Export, Clash, Issue Import", but its steps are a snapshot, a SQLite summary export and a QA/QC check. It never calls Navisworks and never imports clashes. It should not be read as an existing clash loop.
- **Revit side, geometry only.** `revit_check_clashes` (`revit.check_clashes`, read-only) finds clashes between two categories inside Revit. It is separate from Navisworks results.
- **Revit side, element lookup.** `revit_select_by_unique_ids` (`revit.select_by_unique_ids`) takes Revit `UniqueId` strings, resolves them with `doc.GetElement`, and selects them. It only changes the selection, so it is not mutating. The add-in's own comment says `UniqueId` is stable across sessions, unlike `ElementId`. `revit_set_selection` takes `ElementId`.
- **Issue store.** The QA/QC module keeps findings in a per-workspace SQLite store (`qaqc_issues.db`) with a lifecycle, and tools to list and resolve them. That is the closest existing home for a clash-derived issue. Whether its schema fits a clash with two elements is not checked.
- **Fixing tools.** Gated tools for changing parameters and moving elements exist in the Revit provider. Whether they are safe and expressive enough for clash fixes is not checked.
- **Reflection escape hatch.** `navisworks_invoke_method` and `navisworks_reflect_set` exist. They are out of scope here and should not be used to build this loop (see ADR 0013 on the same tool on the Revit side).

## Input formats

### Navisworks clash export
Clash Detective can write a report from a test, as XML, HTML, text or CSV (UNVERIFIED which options a given Navisworks version offers). The XML export lists each clash with its name, status, distance, grid location, and the two items with their paths and properties. Which identifying properties appear for each item depends on what the source model carried into Navisworks, and on the report settings (UNVERIFIED).

Whether to parse these files at all is open. The add-in can already read results live (`navis.get_clash_results`). A file parser is only worth building if people work from exported reports without Navisworks open on the same machine. That is likely for a reviewer who gets a report by email, but it is not confirmed.

### BCF
BCF is a zip of folders, one per topic, each with a `markup.bcf` XML file, optional viewpoint files and snapshot images. Two versions are in use: BCF 2.1 (XML in a zip, widely supported) and BCF 3.0 (adds new fields and a different viewpoint layout). This is general knowledge of the buildingSMART format and has not been checked against the spec text for this record. A topic can reference components by IFC GUID. A viewpoint can carry a camera and a list of components.

Points to settle before writing a reader or writer:

- Which version to write first. BCF 2.1 is the safer target for compatibility. Reading both is desirable.
- Zip hygiene on import. A BCF file is untrusted input: limit entry count and total size, refuse path traversal in entry names, and parse XML with entity expansion off.
- What to do with fields we do not understand. Keep them if the file is round-tripped, drop them if not, and say which.

## The main risk: mapping clash elements to Revit elements
A clash names two items in the federated Navisworks model. The fix has to act on the matching elements in the Revit model. That mapping is where this loop can go wrong, and a wrong match means the assistant proposes moving the wrong wall.

Identifiers in play:

| Identifier | Where it lives | Stable? | Notes |
| --- | --- | --- | --- |
| Revit `ElementId` | Integer, per Revit document | Stable within a file, a poor key across files or versions | `revit_set_selection` uses it. Easy to confuse with other numbers. |
| Revit `UniqueId` | String on every element (`Element.UniqueId`; exact form UNVERIFIED) | Stable across sessions, per the add-in's own comment | `revit_select_by_unique_ids` resolves it. This is the key the fix side should use. |
| IFC GlobalId | 22-character IFC GUID | Depends on the exporter. Revit's IFC export may derive it from the element GUID, depending on settings (UNVERIFIED) | What BCF components normally carry. |
| Navisworks `InstanceGuid` | Generated per Navisworks model item | Not a Revit identifier | Do not use it to find a Revit element. |

What follows:

1. The add-in returns `ifcGuid`, read from a property called `Guid` under the `Item` category. For a model appended from an RVT or NWC file that property may be missing, or may be something other than the Revit `UniqueId` (UNVERIFIED). The code does not check what the value is.
2. For a model that came through IFC, the GUID is an IFC GlobalId. It has to be matched against a Revit `UniqueId` or the IFC GUID parameter. How Revit stores that link, and whether it exists in a given model, needs checking in a live session.
3. Revit `ElementId` values may appear in the Navisworks properties for Revit-sourced items (UNVERIFIED). They are only valid for the exact Revit file that produced the NWC. If the model has been saved, synchronised or upgraded since, the number could point at a different element or none.
4. Linked models, groups and nested families add more cases: the clashing item can be inside a link or a group instance, and the element to edit lives in a different document from the active one.
5. The federated model can be out of date. If the clash came from an older export, the Revit element may have been moved or deleted since.

Rules to keep the mapping honest:

- Treat every mapping as a proposal with a confidence label: matched by `UniqueId`, matched by IFC GUID, matched only by name and category, or unmatched. Show the label in the plan.
- Re-read the element from the live Revit document before proposing a fix. Show its category, family, type, level and location so the coordinator can see it is the right one.
- Never fall back to a guess silently. An unmatched or low-confidence clash is reported as such and gets no proposed fix.
- Reject a mapping if the Revit element's category or name does not agree with the Navisworks item. That cannot prove a match, but it catches gross errors.
- Do not use `ElementId` as the cross-tool key.

## Options

| Option | What it is | Pros | Cons |
| --- | --- | --- | --- |
| A. Read-only triage first | Pull clash results through the existing tools, map them to Revit by identifier, select and report. No Revit changes proposed. | Smallest. Uses code that exists. Tests the mapping risk with no write risk. | Does not yet shorten the fix step. |
| B. Triage plus proposed fix | A, then for each clash propose a move or parameter change as a gated plan. | Delivers the whole loop. | Needs a small, safe vocabulary of fixes. Depends on the mapping being right. A bad proposal looks authoritative. |
| C. BCF only | Import and export BCF zips, no Navisworks link. | Works with any clash tool. Useful on its own. | No clash source. The mapping problem is the same, with IFC GUIDs. |
| D. Parse Navisworks XML/HTML exports | Read exported reports instead of live results. | Works without Navisworks running. | Format varies by version and settings. The most fragile input. Duplicates what the add-in already reads. |
| E. Rely on the cloud issue tool | Push topics to `issues_endpoint` and stop. | Already in the code. | Needs an endpoint and credentials that may not exist. Does nothing for the Revit fix or for BCF files. |

## Decision (recommended)
Do A first, then C, then B. Skip D unless a pilot user shows they only have exported files. Treat E as an optional output, not the foundation.

Reasons: the mapping is the main risk, and A measures it with no write risk. C reuses the same mapping and gives people a file they can hand to others. B only makes sense once A shows that mapping is reliable on real models.

### First small slice
One read-only path, no new write behaviour:

1. Take one clash test GUID. Call the existing `navisworks_get_clash_results`.
2. For each result, try to map both items to Revit elements using whichever identifier from the table is available, and record which kind of match it was.
3. Resolve the matches in the live Revit document. Report per clash: matched, matched with low confidence, or unmatched, with element category, type and level for each match.
4. Write each clash as an issue in the existing QA/QC store (or a new store if its schema does not fit), with both element identifiers and the match kind.
5. Use `revit_select_by_unique_ids` so the coordinator can look at a clash in Revit.

Success for the slice is a number: on a real project, what share of clashes map to the right Revit element on both sides, checked by a person. If that number is poor, the loop is not worth building until the mapping is fixed, and that is a valid outcome.

### Then BCF export and import
- Export: write a BCF 2.1 zip from the stored issues, with IFC GUID references where we have them and a note where we do not. Open it in at least two other tools to check it is accepted (UNVERIFIED).
- Import: read topics and component references, map them as in the slice, store them as issues. Same zip hygiene rules as above.

### Then proposed fixes, behind the gate
For a mapped clash, build a plan with a small set of fix types, for example move one element by a stated offset, or set a parameter. Each plan:

- names the Revit elements by `UniqueId` and shows their current state,
- shows the clash it answers and the mapping confidence,
- goes through the normal approve step, with the plan hash checked at run time (ADR 0008),
- is refused under `approval_mode=auto`,
- writes the usual audit record, so a revert plan is possible.

The assistant should say in plain words which of the two elements it would move and why, and say when it is not sure. Deciding who owns the fix is a coordination question between teams, not something to automate.

## How to verify
All of this needs real software. Nothing below has been done.

| Check | Needs | Status |
| --- | --- | --- |
| `navis.get_clash_results` returns sensible identity for Revit-sourced, IFC-sourced and DWG-sourced items | Navisworks with a federated test model | UNVERIFIED |
| What the `Guid` property under `Item` actually contains for each source type | Navisworks | UNVERIFIED |
| Mapping to Revit `UniqueId` and to IFC GUID works, and what share is right | Navisworks plus the matching Revit model, one real project | UNVERIFIED |
| Behaviour when the Revit model changed after the NWC was made | Both, with an edited model | UNVERIFIED |
| Clashes involving linked models and groups | Both | UNVERIFIED |
| BCF 2.1 export opens cleanly in two other BCF tools | Other BCF software | UNVERIFIED |
| BCF 3.0 files from another tool import correctly | Sample files and the spec | UNVERIFIED |
| Hostile zip is rejected (traversal, huge entries, XML entities) | Unit tests, no Revit needed | Testable in CI once code exists |
| Fix plan is blocked without approval and under `approval_mode=auto` | Revit session | UNVERIFIED |
| Proposed move removes the clash when Navisworks is re-run | Both | UNVERIFIED |

The zip and XML safety tests and the plan-shape tests can run in ordinary CI. Everything about identifiers needs a person with both programs on one real project.

## Phases

| Phase | Work | Size | Needed before it counts as supported |
| --- | --- | --- | --- |
| 1 | Read-only triage slice and a measured mapping rate | Small to medium | Run on one real project; a person checks a sample of matches |
| 2 | BCF 2.1 export and import, safe zip handling | Medium | Round trip through two other tools; hostile-file tests |
| 3 | Gated fix proposals for a small set of fix types | Medium to large | Approval and revert checked in Revit; Navisworks re-run shows the clash gone |
| 4 | BCF 3.0, Navisworks file parsing, cloud issue push | Medium each | Only if a pilot asks for it |

## Consequences
- The first deliverable is a measurement of the mapping problem, not a feature. That is deliberate.
- Clash fixes stay human-approved. The loop saves lookup and drafting time, not the decision.
- We take on a BCF reader that handles untrusted zip files, which is a security surface we do not have today.
- The existing `export_clash_import` recipe name is misleading. Renaming or replacing it should happen with phase 1, so the repo does not suggest a loop that is not there.

## Open questions
1. Which sources do the federated models in a pilot actually come from (RVT, NWC from Revit, IFC)? That decides which identifier is available.
2. What does the add-in's `ifcGuid` value contain for each of those sources?
3. Does the QA/QC issue store fit a two-element clash, or does a clash need its own store?
4. Is there a pilot user who works only from exported Navisworks reports? If not, drop option D.
5. Which BCF version and which tools must we interoperate with first?
6. Which fix types are safe enough to propose automatically, and which should stay as a written suggestion only?
7. In a workshared model, what happens when the element to move is owned by someone else?
8. Is the cloud `issues_endpoint` real for any user, or should that tool be treated as a stub for now?
