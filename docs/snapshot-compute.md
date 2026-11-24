# snapshot_compute: one-call model queries

`snapshot_compute` runs a read-only pipeline over a saved snapshot and returns only the result. Use it when a question would otherwise take many list, inspect or parameter calls. It follows the pattern of composing tool work in one request and keeping intermediate rows out of the model context, without running model-written code.

Take a snapshot first with `snapshot_take` (scope it with `categories` on large models), then pass its `snapshot_id`.

## Pipeline

`steps` is a list of up to 12 objects, run in order. Each step can have:

| Key | Meaning |
|---|---|
| `name` | Step name. Later steps read it as `$name`. Default `stepN`. |
| `from` | `elements` (default), `types`, `relations`, `$<earlier step>` or `link:<snapshot_id>` (see Linked snapshots). |
| `join` | List of `type`, `host`, `level`, `room`, `group`, `hosted`, `relation_out`, `relation_in`, or `{"rel": ..., "as": ..., "kind": ...}`. The related record is added under `as` (default the join name). `hosted` and the relation joins add a list of up to 50 elements. |
| `spatial` | `{"with": "$<earlier step>", "test": ..., "distance": feet, "as": name}`. Adds the rows of that step whose bounding box passes the test (see Spatial joins). |
| `where` | `{"field", "op", "value", "ci"}`, a list (all must match), or `{"all": [...]}`, `{"any": [...]}`, `{"not": {...}}`. Ops: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `nin`, `contains`, `startswith`, `endswith`, `exists`, `empty`. `value: {"field": "path"}` compares two fields of the same row. |
| `group_by` | Path or list of paths. |
| `aggregate` | `{"name": {"op", "field"}}` with `count`, `sum`, `avg`, `min`, `max`, `distinct`, `list`. Without `group_by` it returns one row. |
| `sort` | Path, `{"field", "desc"}` or a list of them. Numbers sort before text; missing values last. |
| `select` | List of paths or `{"field", "as"}`. |
| `limit` | Rows kept by the step. |

A step runs its parts in this order: `from`, `join`, `spatial`, `where`, `group_by` and `aggregate`, `sort`, `select`, `limit`. So `where` can test join and spatial results, and rows are narrowed before a spatial join only in an earlier step.

Top level: `steps` or `query` (one of them); `params` (with `query` only); `return` names the step to return (default the last, or the saved query's `return`); `max_rows` (1 to 1000, default 100) caps rows in the reply while `row_count` gives the total.

Paths are dotted. A parameter yields its value: `params.Mark`, `host.params.Fire Rating`, `type.params.Width`, `location.xyz.2`, `bbox.max.0`.

Numbers compare as numbers, including numeric text such as `"60"`. A comparison between a number and non-numeric text does not match.

## Examples

Doors rated lower than their host wall:

```json
{"snapshot_id": "01J...", "steps": [{
  "join": ["host"],
  "where": [
    {"field": "category", "value": "OST_Doors"},
    {"field": "params.Fire Rating", "op": "lt", "value": {"field": "host.params.Fire Rating"}}
  ],
  "select": [{"field": "params.Mark", "as": "door"}, {"field": "host.params.Fire Rating", "as": "wall"}]
}]}
```

Door count and marks per level:

```json
{"snapshot_id": "01J...", "steps": [
  {"name": "doors", "where": {"field": "category", "value": "OST_Doors"}, "join": ["level"]},
  {"from": "$doors", "group_by": ["level.type_name"],
   "aggregate": {"n": "count", "marks": {"op": "list", "field": "params.Mark"}}}
]}
```

Rooms with no number, largest first:

```json
{"snapshot_id": "01J...", "steps": [{
  "where": [{"field": "category", "value": "OST_Rooms"}, {"field": "params.Number", "op": "empty"}],
  "sort": {"field": "params.Area", "desc": true}, "select": ["uid", "name", "params.Area"]
}]}
```

## Spatial joins

`spatial` compares each row's `bbox` with the `bbox` of every row of an earlier step and adds the matches under `as` (default the earlier step's name), at most 50, plus `<as>_count` with the full number.

| `test` | A row matches when |
|---|---|
| `overlaps` | the two boxes share any point (touching counts). |
| `contains` | the row's box holds the other box. |
| `within` | the row's box lies inside the other box. |
| `within_distance` | the gap between the boxes is at most `distance` (0 to 1000). The gap is 0 when the boxes overlap. |

- Distances are in the snapshot's `bbox` units. Revit's internal unit is feet; that the add-in writes `bbox` in feet is UNVERIFIED in a live Revit.
- A row without a valid `bbox` (missing, not three numbers, or min above max) never matches. `select` drops `bbox`, so keep it in steps a later spatial join reads.
- An element never matches itself (same `uid` and same `_snapshot_id`).
- The number of comparisons is rows with a box times `with` rows with a box. Above 250,000 the step is refused; narrow both sides with `where` in earlier steps.
- Bounding boxes are axis-aligned and larger than the element, so results are candidates, not exact clashes.

Doors whose boxes touch more than one wall:

```json
{"snapshot_id": "01J...", "steps": [
  {"name": "walls", "where": {"field": "category", "value": "OST_Walls"}},
  {"name": "doors", "where": {"field": "category", "value": "OST_Doors"}},
  {"from": "$doors", "spatial": {"with": "$walls", "test": "overlaps", "as": "walls"},
   "where": {"field": "walls_count", "op": "gt", "value": 1},
   "select": ["params.Mark", "walls_count", {"field": "walls.0.uid", "as": "first_wall"}]}
]}
```

## Linked snapshots

`from: "link:<snapshot_id>"` reads the elements of another saved snapshot in the same workspace, for example a snapshot taken in a linked model. Use it to compare a host and a link in one call.

- Each row from a link carries `_snapshot_id`. Host rows do not.
- Joins on link rows (`type`, `host`, `hosted`, relations) look up records in that link's snapshot.
- At most 4 linked snapshots per call. Reading the same link in several steps counts once.
- The id is checked like `snapshot_id`: a plain name of a file in `<workspace>/snapshots/`. A missing or invalid snapshot is refused with the step name.
- The reply lists `linked_snapshots`. `partial_snapshot` is true when the host or any link is partial.
- No link transform is applied. Spatial joins between host and link rows are only meaningful when both snapshots share coordinates (UNVERIFIED for snapshots taken from live linked models).

Walls of the host that overlap walls of a link:

```json
{"snapshot_id": "01J...HOST", "steps": [
  {"name": "link_walls", "from": "link:01J...LINK", "where": {"field": "category", "value": "OST_Walls"}},
  {"name": "host_walls", "where": {"field": "category", "value": "OST_Walls"}},
  {"from": "$host_walls", "spatial": {"with": "$link_walls", "test": "overlaps", "as": "clash"},
   "where": {"field": "clash_count", "op": "gt", "value": 0}, "select": ["uid", "clash_count"]}
]}
```

## Saved queries

`query: "<name>"` runs the pipeline in `<workspace>/queries/<name>.json` instead of `steps`. Names use letters, digits, `_` and `-`, without `.json`; paths are refused. The file is at most 256,000 bytes. Write it with any file tool; there is no separate tool for it.

The file is a list of steps, or an object:

| Key | Meaning |
|---|---|
| `steps` | Required. Steps as above. |
| `return` | Step to return. The call's `return` takes precedence. |
| `params` | Default values for params. |
| `description` | Text for people. |

`{"$param": "name"}` anywhere in `steps` is replaced by the whole JSON value of that param from the call's `params`, or else from the file's `params`. Text is never templated: `"$param"` inside a string stays as it is, and a param value is not searched for more `$param`. The result is checked exactly like inline steps.

Refused: a missing or unreadable file, invalid JSON, unknown top-level keys, a `$param` with no value, a call param the steps do not use, more than 20 params, and param names other than letters, digits and `_`.

`<workspace>/queries/doors_by_mark.json`:

```json
{"description": "Doors whose Mark is in a list.",
 "params": {"category": "OST_Doors"},
 "steps": [{"where": [
   {"field": "category", "value": {"$param": "category"}},
   {"field": "params.Mark", "op": "in", "value": {"$param": "marks"}}
 ], "select": ["uid", "params.Mark"]}]}
```

Call: `{"snapshot_id": "01J...", "query": "doors_by_mark", "params": {"marks": ["D-101", "D-102"]}}`.

## Rule packs

A QA/QC rule can be a pipeline: the rule field `pipeline` holds steps, and each row of the last step is an issue. See [rule-packs.md](rule-packs.md).

## Taking smaller or faster snapshots

`snapshot_take` options that reduce what the add-in reads (issues #289, #290):

| Option | Effect |
|---|---|
| `categories` | Read only these categories, for example `["Doors", "Rooms"]`. |
| `params` | Read only these parameters (up to 100 names such as `"Mark"`, or built-in ids such as `ALL_MODEL_MARK`). The snapshot records `counts.params`, and QA modules treat it as partial for checks that read other parameters. |
| `slice_size` | 10 to 5000. Read about this many elements per Revit turn and assemble the slices into one snapshot. If the model changes between slices, the reply has `changed_during_capture: true`. |
| `base_snapshot_id` | Incremental capture. The add-in re-reads only elements changed since that snapshot (and instances of changed types), lists every element in scope, and the server merges the result with the base into a new full snapshot. |

An incremental capture falls back to a full capture, and says why in `incremental_reason`, when:

- the base is partial (truncated, dirty-only) or was taken with other `categories` or `params`;
- the base has no change-journal position (mock mode or an older add-in);
- the add-in's change journal does not cover the base: another document, a reopen, reload, sync with central, save as, a Revit restart, or a journal that grew past its entry limit;
- the add-in does not return an incremental capture (older add-in);
- the delta cannot be merged (another document, cut short, or an element missing from both).

Whether slices and incremental captures are faster than a full capture on a real model is UNVERIFIED in a live Revit. Whether the change journal sees every change (for example from links, worksharing or undo) is also UNVERIFIED.

## Limits and safety

- Read-only. It reads snapshot and query files in the workspace and never calls Revit.
- No expressions, code or regular expressions are evaluated. Unknown keys, ops, joins, spatial tests and aggregates are refused with a message that names the step.
- At most 12 steps, 50 clauses per `all` or `any`, 6 nesting levels, 50 items per list aggregate, list join or spatial match list, 500 characters per text value, 4 linked snapshots, 250,000 spatial comparisons per step.
- `partial_snapshot: true` means the snapshot hit its size limit or was taken with `params`, so it does not cover the whole model or every parameter.
- Element-to-room joins read `room_uids`, which the add-in extractor does not fill for every element (UNVERIFIED in a live Revit).
