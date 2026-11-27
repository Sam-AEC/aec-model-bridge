# Shareable QA/QC rule packs

A rule pack is a YAML file of QA/QC rules. A firm can keep its naming,
numbering and standards checks in one file, share it, and run it with
`qaqc_checker_run_check`.

## Where packs live

- Built-in packs ship with the server (for example `core`).
- User packs live in `<workspace>/rule_packs/<name>.yaml`. The workspace is the
  first allowed directory of the server.

`run_check(rule_pack="<name>")` and `list_rules(rule_pack="<name>")` resolve a
pack name in this order: built-in first, then the workspace `rule_packs/`
folder. A user pack cannot shadow a built-in. Names may only contain letters,
digits, `_`, `-` and `.`; paths are not accepted, so a pack name can never point
outside those two folders. Packs are re-validated every time they are loaded.

## Tools

| Tool | Reads/writes | What it does |
| --- | --- | --- |
| `qaqc_checker_list_rule_packs` | read-only | Lists built-in and user packs with rule count and validity. |
| `qaqc_checker_validate_rule_pack` | read-only | Schema-checks a YAML file (`path`) or a named pack (`rule_pack`). Returns `errors` and `warnings`, each with `rule_id`, `field` and `message`. Never executes rules. |
| `qaqc_checker_import_rule_pack` | writes a file | Validates `source_path` (inside the workspace) and copies it to `rule_packs/<name>.yaml`. Refuses invalid packs, built-in names, and existing packs unless `overwrite=true`. |
| `qaqc_checker_export_rule_pack` | writes a file | Copies a built-in or user pack to `destination` (a file or folder inside the workspace; default `exports/<name>.yaml`). Refuses to overwrite unless `overwrite=true`. |

All paths are checked with the workspace path-safety helper (symlinks are
resolved), so nothing is read or written outside the workspace.

## Rule format

```yaml
rules:
  - id: door_mark_missing          # required, unique, letters/digits/_-.
    severity: error                # required: error | warning | info
    category: Doors                # optional label
    description: "Door has no Mark."   # required, becomes the issue message
    filter:                        # optional; see operators below
      category: OST_Doors
      parameter: {name: Mark, empty: true}
    assertion: "element_count == 0"    # optional, this is the default
    fix_template: "Set the Mark on '{label}'."   # optional
```

### Operators the engine supports

Filter keys (all must match):

- `category`: a category such as `OST_Doors`, or a list of them.
- `placed`: `true` or `false`.
- `parameter`: `{name: <Parameter>, empty: true}` or `{name: <Parameter>, value: "<text>"}`.
  `value` is an exact text comparison.
- `workset`: exact workset name.
- `family_source`: matches family types by source (for example `inplace`).
  Use it alone; combining it with element filter keys is rejected.

Assertions:

- `element_count == 0`: every element that matches the filter is an issue.
- `all elements have <field>`: matched elements missing that top-level element
  field are issues.

The validator rejects anything else, with the list of supported names in the
message. There is no regular-expression operator, so naming-pattern checks (for
example "door Mark must match `D-###`") cannot be expressed. Filter rules have
no uniqueness operator; a pipeline rule can find duplicate values with
`group_by` and `aggregate`, but its rows are groups, so those issues have no
element.

### Pipeline rules

A rule can use `pipeline` instead of `filter` and `assertion`. It holds
[snapshot_compute](snapshot-compute.md) steps, and every row of the last step
is an issue: `uid` gives the element, and `label` (if a step selects one),
`type_name` or `category` gives the label. Keep `uid` in the rows; a `select`
without it gives issues with no element. A row whose `uid` is not text (for
example a `list` aggregate named `uid`) fails the rule with an error.

```yaml
  - id: door_rating_below_wall
    severity: error
    description: "Door fire rating is lower than the fire rating of its host wall."
    pipeline:
      - join: [host]
        where:
          - {field: category, value: OST_Doors}
          - {field: params.Fire Rating, op: lt, value: {field: host.params.Fire Rating}}
```

- Pipelines can use joins, field-to-field comparisons, `spatial`, `group_by` and
  every other step key, so checks that `filter` cannot express fit in a pack.
- The validator checks the steps without a model and refuses unknown keys, ops,
  joins and aggregates with the step name. A rule with both `pipeline` and
  `filter` or `assertion` is refused.
- `link:` sources are refused in rule packs.
- Relation joins read the snapshot's relations in `run_check` and in the
  reports that run rule packs.
- A server older than this change warns that `pipeline` is an unknown field and
  runs the rule as if it had no filter, so every element becomes an issue. Use
  pipeline rules only with servers that support them.

[`docs/examples/rule_packs/door-room-pipeline.yaml`](examples/rule_packs/door-room-pipeline.yaml)
has the three `door-room-basics` rules written as pipelines, plus the rule
above. On the mock snapshot the three converted rules find the same issues as
the originals (`tests/test_qaqc_pipeline_rules.py`).

[`docs/examples/rule_packs/door-fire-rating.yaml`](examples/rule_packs/door-fire-rating.yaml)
reports doors rated lower than their host wall, doors without a rating, and doors
whose host wall has no rating. Ratings must be numbers in one unit. Set the parameter
name by replacing `Fire Rating` in the pack.

### Classification and COBie packs

Three example packs check asset categories for classification codes and COBie fields:

- [`classification-uniclass.yaml`](examples/rule_packs/classification-uniclass.yaml): Uniclass 2015 code (`Pr_20_93_52`).
- [`classification-omniclass.yaml`](examples/rule_packs/classification-omniclass.yaml): OmniClass number (`23-13 11 11`).
- [`cobie-completeness.yaml`](examples/rule_packs/cobie-completeness.yaml): COBie component name and space, and type name, category and manufacturer.

Each field gets separate rules:

- `*_not_captured` (info): the element has no such parameter in the snapshot. The parameter does not exist on it, or the add-in did not read it. COBie type fields are read from the element's type.
- `*_missing`: the parameter is present but empty.
- `*_format` (classification packs only): the value has the wrong table prefix or separators.

Limits:

- The parameter names (`Uniclass Code`, `OmniClass Number`, `COBie Component Name` and so on) are assumptions. Replace them in the pack with your names. Pipeline paths split at dots, so a name such as `COBie.Component.Name` cannot be read; use a name without dots.
- The category list (doors, windows, mechanical, electrical and plumbing fixtures) is a starting point. Edit the `in` list in each rule.
- The format check looks at the table prefix and the separators only. The engine has no regex operator, so it does not check the digit groups. For the full pattern, save a reviewed naming rule with `target: parameter`.
- The packs are tested on fixture snapshots only. How the add-in captures these parameters in a live Revit model is UNVERIFIED.

Stored findings belong to their rule pack. Running one pack only reconciles that
pack's issues, and identical rule IDs in different packs stay independent.
Overwriting a pack refreshes its open issues' severity and message on the next run.
Existing databases migrate without deleting history; older issues without a pack
identity are assigned to `core`.

## Reviewed naming rules

A rule pack has no regular-expression operator. A naming rule is a separate, saved
kind of rule: a category, a regex the name must fully match, a message and a severity.
An agent can write one during a chat. It is kept only after a person approves it, and
it runs later with no model call.

| Tool | Reads/writes | What it does |
| --- | --- | --- |
| `qaqc_checker_test_naming_rule` | read-only | Runs a proposed rule against a snapshot. Returns the rule hash, `matches` and `misses`, each with a count and a sample (default 10, at most 25). Saves nothing. |
| `qaqc_checker_save_naming_rule` | mutating | Writes `<workspace>/naming_rules/<rule_id>.json`. It is gated like any write: `plan_actions`, a person approves the plan in the panel, then `execute_plan`. It is not a human-only tool, and it cannot run without an approved plan unless the person has switched approval off. Refuses an existing id unless `overwrite=true`. |
| `qaqc_checker_replay_naming_rules` | appends to a log | Runs every saved rule (or the ids in `rule_ids`) against a snapshot. No model call. The same snapshot gives the same findings, sorted by rule id and element uid. Returns `rule_hashes` and writes them to `<workspace>/naming_rules_audit.jsonl` with the snapshot id. |

`target` picks the value that is checked: `type_name` (default), `name`, `family`, or
`parameter` together with `parameter` (the parameter name). Elements are matched by
`category`. An empty value, or a value longer than 128 characters, is a miss and is not
passed to the regex.

The rule hash is the SHA-256 of the rule fields as sorted compact JSON. The rule file
stores it. Replay recomputes it and refuses a file that was edited, that has an invalid
regex, or whose id does not match its file name. Rule ids use the pack-name character
set and are built with the workspace path-safety helper, so a path never reaches the file
system.

### Which regexes are refused

Python's `re` has no timeout, so the check is made before the pattern runs. A regex is
refused when it:

- is empty, longer than 200 characters, or does not compile;
- uses a backreference or a lookaround;
- puts a variable repeat (`+`, `*`, `?`, `{m,n}`) inside another repeat, for example `(a+)+` or `(\w+\s?)+`;
- puts an alternation inside a repeat, for example `(a|aa)+`;
- has more than 3 unbounded repeats.

Safe patterns such as `[A-Z]{1,3}-\d{3}` or `(A|B)-\d+` pass. Together with the 128
character cap on names, the work per element stays small.

## Example pack

[`docs/examples/rule_packs/door-room-basics.yaml`](examples/rule_packs/door-room-basics.yaml)
covers door Mark, unplaced doors and room Number. To use it:

1. Copy the file into your workspace, for example `<workspace>/door-room-basics.yaml`.
2. `qaqc_checker_validate_rule_pack` with `path` set to that file.
3. `qaqc_checker_import_rule_pack` with `source_path` set to that file.
4. `qaqc_checker_run_check` with `rule_pack="door-room-basics"`.

To share your own pack, call `qaqc_checker_export_rule_pack` and send the
resulting YAML file; the recipient imports it the same way.

## IDS validation

`ids_validator_validate_ifc` checks an IFC file against a buildingSMART IDS file (`.ids` XML) with `ifctester` from IfcOpenShell. Both files must be inside the workspace. It needs the optional extra and refuses with an install hint without it:

```
pip install "aec-model-bridge[ids]"
```

The result gives pass, fail or skipped per specification (skipped means the specification is for another IFC schema version), the applicable, passed and failed entity counts, the failing GlobalIds with their class, name and reasons (at most `max_failed` per specification, default 50; the counts stay complete), and the requirement summary. `html_filename` and `json_filename` write a report inside the workspace. The IFC and IDS files are only read. This is separate from the rule packs above, which run on snapshots. `ifctester` is limited to 0.8.x because 0.9 needs a newer IfcOpenShell than this project locks.
