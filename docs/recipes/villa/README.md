# Villa recipes (IronPython for revit_execute_python)

`prelude.py` is the helper prelude that the villa build scripts ran after. The one-off phase scripts were removed;
the repository history keeps them. The reusable parts are now tools (see `docs/recipes-library.md` and the `revit_*` tool list).

Hard-won facts the phase scripts encoded:
- Layered types: duplicate an existing type's own compound structure (`SetLayers`), keep Revit's layer order
  (substrate < insulation < membrane < finish outside the core); membrane layers must be 0 mm thick.
- Walls drawn counter-clockwise face inwards: measure `Wall.Orientation` and `Flip()`.
- Host openings only in walls that reach above the floor, not the underground foundation walls.
- `NewFootPrintRoof` cannot be called from IronPython (out parameter); use the add-in command.
- Copying families between documents needs an `IDuplicateTypeNamesHandler`, or Revit shows a blocking dialog.
- Failure handler: collect warnings, remove only a failing door/window, roll back anything else; never show a dialog.
- Verify by measurement: type thickness, element z-ranges, wall volume drops for each opening, room areas, stair
  risers, warning count before and after.
- Tag what a phase creates (`Comments = AMB_VILLA:<phase>`) so it can be re-run; floors need the fallback tagging in the prelude.
