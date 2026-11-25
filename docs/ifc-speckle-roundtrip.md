# IFC and Speckle exchange round trip (mock mode)

`examples/ifc-speckle-roundtrip.ipynb` walks an exchange round trip in mock mode: snapshot, IFC export plan, IFC checks, a comparison with the snapshot, and a Speckle send plan. It needs no Revit, no Windows and no network. Nothing is approved or executed.

Run it from `packages/mcp-server-revit` after `uv sync --all-extras`:

```bash
uv run --with jupyter jupyter lab ../../examples/ifc-speckle-roundtrip.ipynb
```

Each run writes to a new temporary workspace folder. `tests/test_ifc_speckle_roundtrip_notebook.py` runs every code cell in mock mode, once with `ifcopenshell` and once with it blocked.

## Steps

| Step | Tools | In this notebook | With a live Revit or Speckle server |
|---|---|---|---|
| 1. Snapshot | `snapshot_take`, `snapshot_compute` | Mock snapshot: 2 levels, 1 wall, 1 door, 2 rooms. One `snapshot_compute` call returns count, type names and `FireRating` per category. | Same calls on the open model. UNVERIFIED in this notebook. |
| 2. Export to IFC | `plan_actions` with `revit_export` (`format: ifc`) | The plan is drafted and stays `pending`. Mock mode cannot write an IFC, so the notebook copies the test fixture `tests/data/ids/tiny.ifc` (IFC4, 3 walls, 1 door) and `tiny.ids` into the workspace. | A person approves the plan and `execute_plan` writes the file. UNVERIFIED. |
| 3. Read and check the IFC | `ifc_get_metadata`, `ifc_validate`, `ids_validator_validate_ifc` | Real: IfcOpenShell reads the fixture. `ifc_validate` reports one schema error (the door GlobalId is not valid base64). The IDS check passes 1 of 2 specifications: walls B and C have no `Pset_WallCommon.FireRating`. | Same tools on the exported file. |
| 4. Compare with the snapshot | `ifc_query_elements`, `ifc_get_properties`, `revit_ifc_check` | Counts per class and `FireRating` on both sides. The fixture is not an export of the mock model, so walls differ (1 against 3) and doors match (1 against 1). `revit_ifc_check` reads the IFC side only and returns verdict `UNVERIFIED` in mock mode. | `revit_ifc_check` compares the file with the live model. UNVERIFIED. |
| 5. Speckle | `speckle_auth_status`, `plan_actions` with `speckle_send_object` | `speckle_auth_status` is offline and reports `authorized: false`. The send is drafted as a plan and stays `pending`. `speckle_receive_object` is skipped and labelled "requires a Speckle server". `PROJECT_ID` and `VERSION_ID` are placeholders. | Send and receive need a Speckle server and a local Speckle account. UNVERIFIED. |

## Mock and real

- Real in the notebook: the server's tool handlers, the approval gate, IfcOpenShell reading and validating the fixture, the IDS check with `ifctester`, and the counts and property comparison.
- Mock in the notebook: the Revit model (a fixed mock snapshot) and the IFC file (a test fixture instead of an export).
- Not run: the IFC export, the comparison against a live model, and any Speckle network call. The Speckle provider has no dry-run mode; network tools are only drafted into plans.

## Optional packages

- Without `ifcopenshell`, steps 2 to 4 print `SKIPPED` and the notebook still runs steps 1 and 5. The export plan is still drafted.
- Without `ifctester` (the `ids` extra), the IDS check prints `SKIPPED`.
- Without the Speckle provider, step 5 prints `SKIPPED`.

## Related

- [snapshot_compute](snapshot-compute.md): the pipeline used in step 1.
- [BCF issue exchange](bcf-exchange.md): issues in and out of `.bcfzip`.
- `examples/mock-tour.ipynb`: a shorter mock-mode tour from `revit_get_context` to a pending plan.
