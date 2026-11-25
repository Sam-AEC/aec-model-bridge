# Villa 2 recipes (DWG to Revit)

Kept files for the villa drawn in a DWG (ground plan, first-floor plan, four elevations). The one-off phase scripts
(types, walls, floors, openings, stair, roofs, views) were removed; the repository history keeps them.

| File | Use |
|---|---|
| `prelude.py` | Helper prelude (`# prelude2` marker in the helper client) |
| `m1_specs.json` | Family spec format read by `revit_make_family` and the MEP tools |
| `m1_mep_families.py` | Original MEP family builder; `revit_make_family` is ported from it |
| `m3_route.py`, `m4_heating.py`, `m7_electrical.py` | Original pipe, duct and cable routing recipes; the `revit_mep` tools are ported from them |
| `../toolkit/audit_villa.py` | Measured audit of openings and roofs; ported to `revit_audit_openings` and `revit_audit_roofs` |
| `../toolkit/intersections.py` | Wall, floor and roof solid overlaps in m3; ported to `revit_check_intersections` |

Scale: 1 DWG unit = 0.125 m. All DWG coordinates are in the ground-plan frame (first-floor drawing minus (214.0, 2.4)).

Lessons (also in the `revit-bim-builder` skill): draw exterior walls with the exterior on the LEFT of the direction instead of calling `Flip`;
walls stop at slab undersides; a single `revit_execute_python` call must stay under 30 s (families one per call);
arch openings are cut with void-family instances, not with a family Opening.
