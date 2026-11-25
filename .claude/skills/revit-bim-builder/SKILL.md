---
name: revit-bim-builder
description: Build or modify BIM content in a live Revit session through AEC Model Bridge (revit_execute_python, revit_raw_command). Use for any task that creates walls, floors, roofs, openings, rooms, stairs, families, views or sheets. Encodes the verified workflow and the Revit API traps found in live use.
---

# Build, measure, review, repeat

A model is not done when the commands succeed. It is done when it has been measured and an independent reviewer
(the `bim-reviewer` agent, or `scripts/revit/bim_review/bim-review.ps1`) finds nothing. Published text-to-BIM benchmarks
put the best models near 50%, with failures in spatial reasoning and consistency, so assume your first attempt has
defects and build the loop in.

## Loop
1. Plan on paper first: grid, levels, rooms, adjacency, circulation, structure, openings. Write the plan in the reply.
2. Build one phase per script (types, structure, openings, rooms, stair, content, documentation).
   Every phase: tag what it creates (`Comments = AMB_VILLA:<phase>`) so it can be re-run, run inside one transaction with
   the failure handler in `docs/recipes/villa/prelude.py`, and print measured results.
3. Measure, never assume: element z-ranges, type thickness, wall volume before/after an opening, room areas, risers,
   warning count before and after, orientation by probing a point outside the wall.
4. Render the views to PNG and LOOK at them. Image review caught a swinging garage door, a blank 3D view and a section
   that was not a cut.
5. Run the reviewer. Fix every FAIL. Repeat until it passes, then report the numbers.

## Units, coordinates, levels
- Revit internal length is feet. millimetres / 304.8. metres / 0.3048.
- Build on the real ground level of the project, not on the level the anchor element happens to sit on.
- Tie wall tops to levels (top constraint + offset). Unconnected heights are a defect.

## Traps (all hit in live use)
- Invented API members: check any member you have not used before with `revit_api_lookup` (offline docs, says the Revit year).
- IronPython 2.7 has no standard library (`collections` is missing). `Element.Name` can fail: use
  `get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)` or the room name parameters.
- Methods with `out` parameters cannot be called from IronPython (`NewFootPrintRoof`): use the add-in command
  `revit.create_roof`, or call by reflection.
- Compound structures: edit the duplicated type's own structure (`SetLayers`) so the end-cap condition is right;
  layers outside the core must follow Revit's order (substrate, insulation, membrane, finish); membrane layers are 0 mm.
- Walls drawn counter-clockwise face inward. Probe 0.6 m along `Wall.Orientation`: that point must not be inside a room.
- Hosted openings: pick the host among walls that reach above the floor, not the underground foundation wall;
  verify each opening by the host wall's volume dropping.
- A 4.8 m "door" made from a hinged-door family shows a giant swing arc: use a non-swinging type.
- Copying families between documents shows a blocking Duplicate Types dialog unless you pass an
  `IDuplicateTypeNamesHandler` returning `UseDestinationTypes`.
- Revit dialogs freeze the bridge. Collect warnings in an `IFailuresPreprocessor`; remove only a failing door/window,
  roll back anything else. A swallowed warning is still a defect: re-measure the warning count afterwards.
- Floors keep Comments under a different parameter than walls: tag with the fallback in the prelude.
- Bridge requests time out at 30 s. Keep a script under about 20 s; export one image per call.
- Placing content: never type coordinates for a fixture from assumptions. A family's origin is not its centre, rotation is
  about the origin, a bounding box includes hidden extent, and `FacingOrientation` means different things per family
  (WC: points to the back; bed: sideways). Measure the real geometry (mesh/solid vertices), find the back/head from the
  geometry, rotate, then move so the visible edge touches the wall face.
- Level-based families: the placement z is an offset FROM the level. Pass 0.
- `get_BoundingBox`/geometry are `None` until `doc.Regenerate()` inside the transaction; calling it outside one raises.
- Phase-indexed properties (`FromRoom`, `ToRoom`, `Room`) show as `indexer#` in IronPython: use `get_FromRoom(phase)`.
- `Wall.Flip()` after creation breaks corner joins. Revit puts the exterior face on the LEFT of the drawing direction: reverse the curve before creating the wall.
- Walls stop at the slab underside (top offset = slab thickness); slabs run to the outer wall faces. Check overlaps with solid intersection, not bounding boxes.
- Diagonal walls: build from exact dx == dy ("slightly off axis" otherwise). When snapping wall ends, keep a minimum length ("curve length too small").
- A floor type duplicated from the project's first `FloorType` may be a foundation slab: assert `IsFoundationSlab == False`.
- Levels made through the API have no plan view; create it first. Setting `VIEW_NAME` on a level's own plan view renames the level.
- A never-opened 3D view exports blank: crop it to the section box before `ExportImage`. `revit_export_image` can report `file_exists:false`; export with `ImageExportOptions` and list the folder.
- `revit_execute_python` has a new scope per call. Commit or roll back a `Transaction` inside the same call.
- Pass `helpers: true` for the `amb` library: quick-filter collectors, parameter and box filters, unit conversion, and in write mode `amb.batch` (one transaction, `SubTransaction` per item). Error line numbers then include the helper lines. See `docs/python-automation.md`. UNVERIFIED in live Revit.
- A bridge timeout does not stop Revit; the result is lost. Split long work (one family per call), then verify with a read-only audit. `revit_health` returns only when the queue is idle.
- A door or window wider than its wall piece rolls back the whole transaction: check fit first. Place openings one per transaction.
- Setting `Width`/`Height` type parameters on a generated family from the project rescales its geometry: set them inside the family. Window geometry must start at the Sill reference plane.
- A generic base family can carry nested content (a "Pole" held a wallbox): delete nested instances and probe the result.
- Close `EditFamily` documents in `finally`; an uncommitted transaction in a temporary document blocks `Close`.
- Reading a DWG: `app.NewProjectDocument` plus `Document.Import` in the temporary document, read the geometry, close it. The project is untouched.
- The model may start with thousands of warnings. Measure deltas, never absolutes.
- Never kill processes by name (`Stop-Process -Name python` killed MCP servers); target by command line.

## Content
Use families that exist in the model or the user's libraries (the project's own furniture, planting, structural
families), found with `revit_list_commands`/`list_families`, not generic guesses. The Autodesk content folder on this
laptop holds structural and annotation content only: no doors, windows, furniture or planting.

## Never
- Never call a model finished on the strength of your own summary.
- Never delete or alter elements you did not create. Tag what you create; remove by tag.
