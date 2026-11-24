# snapshot_compute: one-call model queries

`snapshot_compute` runs a read-only pipeline over a saved snapshot and returns only the result. Use it when a question would otherwise take many list, inspect or parameter calls. It follows the pattern of composing tool work in one request and keeping intermediate rows out of the model context, without running model-written code.

Take a snapshot first with `snapshot_take` (scope it with `categories` on large models), then pass its `snapshot_id`.

## Pipeline

`steps` is a list of up to 12 objects, run in order. Each step can have:

| Key | Meaning |
|---|---|
| `name` | Step name. Later steps read it as `$name`. Default `stepN`. |
| `from` | `elements` (default), `types`, `relations` or `$<earlier step>`. |
| `join` | List of `type`, `host`, `level`, `room`, `group`, `hosted`, `relation_out`, `relation_in`, or `{"rel": ..., "as": ..., "kind": ...}`. The related record is added under `as` (default the join name). `hosted` and the relation joins add a list of up to 50 elements. |
| `where` | `{"field", "op", "value", "ci"}`, a list (all must match), or `{"all": [...]}`, `{"any": [...]}`, `{"not": {...}}`. Ops: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `nin`, `contains`, `startswith`, `endswith`, `exists`, `empty`. `value: {"field": "path"}` compares two fields of the same row. |
| `group_by` | Path or list of paths. |
| `aggregate` | `{"name": {"op", "field"}}` with `count`, `sum`, `avg`, `min`, `max`, `distinct`, `list`. Without `group_by` it returns one row. |
| `sort` | Path, `{"field", "desc"}` or a list of them. Numbers sort before text; missing values last. |
| `select` | List of paths or `{"field", "as"}`. |
| `limit` | Rows kept by the step. |

Top level: `return` names the step to return (default the last); `max_rows` (1 to 1000, default 100) caps rows in the reply while `row_count` gives the total.

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

- Read-only. It reads a snapshot file in the workspace and never calls Revit.
- No expressions, code or regular expressions are evaluated. Unknown keys, ops, joins and aggregates are refused with a message that names the step.
- At most 12 steps, 50 clauses per `all` or `any`, 6 nesting levels, 50 items per list aggregate or list join, 500 characters per text value.
- `partial_snapshot: true` means the snapshot hit its size limit or was taken with `params`, so it does not cover the whole model or every parameter.
- Element-to-room joins read `room_uids`, which the add-in extractor does not fill for every element (UNVERIFIED in a live Revit).
