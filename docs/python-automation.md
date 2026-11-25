# Python automation in Revit

How to write fast `revit_execute_python` scripts, and the `amb` helper library that the server can put before a script. The approval rules do not change: `mode='read'` needs no approval and cannot open transactions; `mode='write'` (the default) needs an approved plan.

Status: the helpers and the patterns below have not run in a live Revit session (UNVERIFIED). Server-side behaviour (when the prelude is added, read-mode checks) is covered by `tests/test_python_helpers.py`.

## Engines and syntax

The add-in runs IronPython 2.7 on Revit 2024 (net48) and IronPython 3.4 on Revit 2025 and later (net8, net10). A script that must run on both uses the shared subset:

- No f-strings. Use `"%d walls" % n` or `"{0} walls".format(n)`.
- `print(x)` with one argument only. `print(a, b)` prints a tuple on 2.7.
- No annotations, keyword-only arguments, `nonlocal`, `yield from` or `a, *b = ...`.
- No `long`, `basestring`, `unicode` or `xrange` (missing on 3.4); no `json` module on some 2.7 builds.
- Use `//` for whole-number division.

Check any API member you have not used before with `revit_api_lookup`.

## Turning the helpers on

```json
{"script": "print(amb.count(amb.instances('Walls')))", "mode": "read", "helpers": true}
```

- `helpers: true` puts the helper text before the script. Without it nothing is added.
- Read mode gets the read part only (`python_helpers/amb_read.ipy`). The server checks the caller's script, then checks the combined text again. The add-in repeats its own text check and keeps its roll-back guard. A read-mode script that names `Transaction` is refused with or without helpers.
- Write mode also gets the write part (`python_helpers/amb_write.ipy`): batched transactions, sub-transactions and transaction groups.
- Error line numbers count the helper lines. The helpers end with a marker line `# ---- end of AEC Model Bridge helpers (amb) ...`; the caller's script starts on the next line.
- A script with `from __future__ import ...` is refused when `helpers` is true, because that import must be the first statement.
- `revit_run_job` takes the same `helpers` flag for scripts.
- Saved recipes (`revit_recipe_run`) always get the read part; a recipe that runs as write also gets the write part.

## Read helpers

All helpers are static methods of `amb`. Lengths are Revit internal units (feet) unless a unit is named.

| Helper | What it does |
|---|---|
| `amb.instances(cats, view=None)` | Placed elements of one or more categories: `OfCategory` or `ElementMulticategoryFilter`, then `WhereElementIsNotElementType` |
| `amb.types(cats)` | Element types of one or more categories |
| `amb.of_class(cls, view=None)` | `OfClass` collector |
| `amb.collector(view=None, ids=None)` | Plain collector over the document, one view, or a set of ids |
| `amb.ids(col)` / `amb.count(col)` / `amb.first(col)` / `amb.take(col, n)` | Results without loading every element |
| `amb.where(col, param, op, value)` | One `ElementParameterFilter` rule |
| `amb.rule(...)` / `amb.where_all(col, rules)` | Several rules that must all match |
| `amb.in_box(col, lo, hi, inside=False)` | `BoundingBoxIntersectsFilter` or `BoundingBoxIsInsideFilter` |
| `amb.near_point(col, pt)` | `BoundingBoxContainsPointFilter` |
| `amb.intersecting_solid(col, solid)` / `amb.intersecting_element(col, e)` | `ElementIntersectsSolidFilter` / `ElementIntersectsElementFilter` |
| `amb.solids(e)` / `amb.box_solid(lo, hi)` | Solids of an element; a transient box solid |
| `amb.to_internal(v, unit)` / `amb.from_internal(v, unit)` | `UnitUtils` with `UnitTypeId` (`mm`, `cm`, `m`, `ft`, `in`, `m2`, `ft2`, `m3`, `ft3`, `deg`, `rad`) |
| `amb.dependents(e, element_filter=None)` | `Element.GetDependentElements` as integer ids |
| `amb.value(e, param, unit=None)` / `amb.parameter(e, param)` | Parameter value by storage type |
| `amb.eid(x)` / `amb.element_id(x)` / `amb.id_list(ids)` | Ids across Revit versions (`ElementId.Value` on 2024+) |
| `amb.bic(name)` | `'Walls'`, `'OST_Walls'` or `'Structural Framing'` to `BuiltInCategory` |

`param` is a `BuiltInParameter`, its name (`'ALL_MODEL_INSTANCE_COMMENTS'`), an `ElementId`, or a project or shared parameter name. `op` is one of `==`, `!=`, `>`, `>=`, `<`, `<=`, `contains`, `not_contains`, `begins`, `not_begins`, `ends`, `not_ends`, `has_value`, `no_value`. A float value compares with `epsilon` (default `1e-6`, internal units). Pass a float for a length, area or angle parameter (`3.0`, not `3`): an int value builds an integer rule, which does not match a double parameter. Text rules use the two-argument factory methods of Revit 2023 and later (not case sensitive) and fall back to the older overload.

## Write helpers (write mode only)

| Helper | What it does |
|---|---|
| `amb.run(name, fn, *args)` | `fn` in one transaction; commit on return, roll back and re-raise on error |
| `amb.batch(name, items, fn, max_failures=None)` | All items in one transaction, each in its own `SubTransaction`; returns `(done, failed)` |
| `amb.try_sub(fn, *args)` | `fn` in a `SubTransaction` inside an open transaction; returns `(True, result)` or `(False, message)` |
| `amb.group(name, [(step, fn), ...])` | Each step in its own transaction inside a `TransactionGroup` that is assimilated into one undo entry |
| `amb.set(e, param, value, unit=None)` | Set a parameter by storage type, converting a unit first |
| `amb.regenerate()` | `doc.Regenerate()` once after a batch |

Transactions come from `amb_transaction(doc, name)`, which the add-in defines in write mode: warnings are dismissed without a dialog and returned in the result's `warnings`, and errors roll the transaction back. If it is missing, the helpers use a plain `Transaction` with their own `IFailuresPreprocessor` set through `FailureHandlingOptions`.

## Patterns and why they are faster

### Quick filters first, then slow filters

Revit checks quick filters (category, class, element type flag, bounding box) against element records without loading the element. Slow filters (parameter rules, solid intersection) load each element. Apply quick filters first so the slow filter sees fewer elements.

```python
col = amb.instances(["Walls", "Floors"])             # quick
col = amb.in_box(col, (0, 0, 0), (50, 50, 12))       # quick
col = amb.where(col, "ALL_MODEL_INSTANCE_COMMENTS", "begins", "AMB_")  # slow, now on fewer elements
print(amb.count(col))
```

### Ids, not elements

`ToElements()` and iterating a collector build one Python wrapper per element. `ToElementIds()`, `GetElementCount()` and `FirstElement()` do not. Fetch elements only for the ids you print or change.

```python
ids = amb.ids(amb.instances("Doors"))
print(len(ids))
for e in amb.elements(ids[:20]):
    print(e.Name)
```

### Filter parameters inside Revit

A Python loop that reads a parameter on every element crosses the .NET boundary twice per element. An `ElementParameterFilter` runs the comparison in native code.

```python
# Walls taller than 3 m
tall = amb.where(amb.instances("Walls"), "WALL_USER_HEIGHT_PARAM", ">", amb.to_internal(3.0, "m"))
```

The same rule without the helpers:

```python
from Autodesk.Revit.DB import *
provider = ParameterValueProvider(ElementId(BuiltInParameter.WALL_USER_HEIGHT_PARAM))
rule = FilterDoubleRule(provider, FilterNumericGreater(), 3.0 / 0.3048, 1e-6)
walls = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Walls) \
    .WhereElementIsNotElementType().WherePasses(ElementParameterFilter(rule))
```

### Spatial filters

`BoundingBoxIntersectsFilter` and `BoundingBoxIsInsideFilter` are quick filters. `ElementIntersectsSolidFilter` tests real geometry and is slow, so narrow with a box first.

```python
lo, hi = (0, 0, 0), (30, 30, 10)
near = amb.in_box(amb.instances(["Ducts", "Pipes"]), lo, hi)
hits = amb.intersecting_solid(near, amb.box_solid(lo, hi))
```

### One transaction for many changes

Each transaction regenerates the model and adds an undo entry. One transaction for a batch regenerates once. A `SubTransaction` per item lets one bad item roll back alone.

```python
ids = amb.ids(amb.where(amb.instances("Doors"), "ALL_MODEL_INSTANCE_COMMENTS", "no_value"))
done, failed = amb.batch("Tag doors", amb.elements(ids),
                         lambda e: amb.set(e, "ALL_MODEL_INSTANCE_COMMENTS", "AMB_CHECKED"))
print("%d set, %d failed" % (len(done), len(failed)))
```

Use `amb.group` when steps must be separate transactions (for example a regenerate between them) but should undo as one.

### Units

`UnitUtils.ConvertToInternalUnits(value, UnitTypeId.Millimeters)` replaces hand-written factors and covers areas, volumes and angles. `amb.mm(v)` divides by 304.8 without a Revit call for tight loops.

### Dependent elements

`Element.GetDependentElements(filter)` returns hosted and owned elements (doors in a wall, tags, sketch lines) in one call. Use it before deleting or moving an element to see what goes with it.

```python
wall = amb.first(amb.instances("Walls"))
print(amb.dependents(wall, amb.category_filter(["Doors", "Windows"])))
```

## Keep scripts short

A script runs on Revit's user-interface thread and cannot be cancelled. Keep each call well under 20 seconds, work from ids, and split long work over several calls or `revit_run_job`.

## Recipes that use the helpers

Two read-only starter recipes use `amb`: `elements_by_parameter` (one category plus one parameter rule) and `elements_in_box` (categories plus a box in metres). See [recipes-library.md](recipes-library.md).

## Related

- [ADR 0019](adr/0019-optional-cpython-engine.md): optional CPython 3 engine for numpy and pandas (proposal).
- [Recipe library](recipes-library.md): saved scripts with checked parameters.
- [Security model](security.md): what read mode does and does not protect.
