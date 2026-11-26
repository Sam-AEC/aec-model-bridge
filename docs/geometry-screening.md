# Geometry screening

`geometry_screening_run_checks` screens a saved snapshot with four repeatable geometric checks. It is a screening aid, not a code compliance check. A person reads the findings and decides. Results on a real model are UNVERIFIED until checked in a live Revit.

It is read-only. It reads `snapshots/<snapshot_id>.json` in the workspace and never calls Revit. The same snapshot and settings always give the same result.

## Checks

Pass one or more of these objects. Thresholds are in metres and square metres, and so are the results.

| Check | Settings | Finding when |
|---|---|---|
| `room_area` | `brief`: list of `{match, min_m2, max_m2}` | A room is below `min_m2` or above `max_m2`. `match` is a room number or name (name not case sensitive). |
| `door_width` | `min_clear_width_m`, optional `width_parameter` | A door is narrower than the minimum. Reads `Clear Width`, else `Width`, on the door, else on its type. |
| `turning_circle` | `diameter_m`, `rooms` (numbers or names) | The largest circle inside the room outline is smaller than `diameter_m`. Accurate to 1 mm. |
| `travel_distance` | `exit_rooms`, `max_m`, optional `from_rooms` | The shortest route from a room centroid to an exit room is longer than `max_m`, or there is no route. |

Other inputs: `snapshot_id`, `snapshot_units` (`feet`, the Revit internal unit and the default, or `metres`) and `max_items` (listing cap per check; counts stay complete).

Each finding has `element_ids` (Revit ids), `uids`, `measured`, `threshold`, `threshold_kind` (`min` or `max`), `unit` (`m` or `m2`) and a plain `message`. Travel findings add `path_uids`: the rooms and doors along the shortest route. Each check also reports `checked`, `passed`, `failed` and `skipped` (elements it could not measure, with the reason).

## Travel distance method

Rooms are nodes. A door with a room on both sides (`From Room`, `To Room`) joins them. An edge is the straight distance from one room centroid to the door point plus the door point to the other centroid. The result is the shortest path to any room named in `exit_rooms`. Straight lines through rooms are assumed to be walkable; furniture, walls inside a room and stairs are not modelled. A door with no room on one side is not an edge.

## Data the snapshot must hold

The check refuses with a plain error when what it needs is missing. It does not guess.

| Data | Where | Used by |
|---|---|---|
| Room outline | `geometry_ref.boundary` on the room: one closed outline as `[[x, y], ...]` in plan (outer loop only, no holes) | `turning_circle`, `travel_distance`, `room_area` (the `Area` parameter is a fallback) |
| Door room keys | `From Room` and `To Room` parameters (room uids), from `snapshot_take` with `include: ["rooms"]` | `travel_distance` |
| Door location | `location.xyz` | `travel_distance` |
| Door width | `Clear Width` or `Width` on the door or its type | `door_width` |

The Revit add-in does not write room outlines into snapshots yet, so `turning_circle` and `travel_distance` refuse on a snapshot taken today, and `room_area` works only through the `Area` parameter. Add-in output for `geometry_ref.boundary` is UNVERIFIED; the checks are tested on fixture snapshots only. The `Width` parameter is the nominal opening width, not a measured clear width, so each finding names the parameter it used.
