# Proof bundles and revert plans

Every plan that finishes executing leaves a proof file, and an executed parameter fix can be undone through the same approval gate.

## Proof bundle

When `execute_plan` finishes (or a mutating tool marks a plan executed), the server writes `proofs/<plan_id>.json` in the workspace. Read it with the read-only tool `get_proof_bundle(plan_id)`.

| Field | Meaning |
| --- | --- |
| `plan_id`, `tool`, `tools` | The plan and the tool(s) it called. |
| `created_at`, `approved_at`, `executed_at` | Lifecycle timestamps (UTC). |
| `approved_by` | Name passed as `approver` to `approve_plan`. Self-reported and not authenticated; `null` if none was given. |
| `document` | `snapshot_id`, `doc_guid`, `doc_title` of the snapshot the plan was drafted from. `null` if the plan has no `snapshot_id`. |
| `plan_hash` | SHA-256 of the plan content (actions, arguments, before values, skipped list). |
| `elements` | Applied changes: `element_id`, `uid` (when a snapshot is known), `parameter`, `before`, `new`. |
| `skipped` | Elements left out, each with a `reason` (blocked at planning time, or failed at execution). |
| `outcome` | `success`, `partial` or `failed`. Only `success` means every action ran. |

To get the document identity and the skipped list, pass `snapshot_id` (and `skipped`, which `parameter_manager_plan_set_params` returns as its blocked list) to `plan_actions`.

## Reverting

`plan_revert(plan_id)` reads the proof bundle and drafts a new pending plan that sets each parameter back to its recorded `before` value. It never executes anything: the draft still needs `approve_plan` and `execute_plan`, and its own execution gets its own proof (`reverts_plan_id` links them).

It refuses, with a message, when:

- the plan has no proof bundle, or its outcome is not `success` (partial and failed runs are not reverted);
- the plan state is not `executed`;
- an element has no recorded `before` value (an empty value counts as not recorded);
- the current model value differs from the value the plan wrote. With `allow_conflicts=true` the draft is created anyway and lists those elements under `conflicts` for explicit review.

Like `plan_actions`, drafting a revert is not itself gated; changing the model is.

## Limitations

- UNVERIFIED: write-back to Revit. The tests use an in-memory fake parameter store. The `outcome` reflects what the provider reported; the server does not re-read values after writing. Confirm against a live Revit session before relying on it.
- UNVERIFIED: revert's staleness check and the `before` capture read values through `revit_get_parameter_value`, so their correctness in a real model (units, type vs instance parameters, worksharing ownership) depends on that live tool.
- When a mutating tool is called directly with a `plan_id` (not through `execute_plan`), no per-action results exist. The proof is still written, but its outcome is never `success`, so such plans cannot be reverted. Direct calls that raise before the plan is marked executed leave no proof.
- Only `revit_set_parameter_value` actions are recorded per element and reverted. Other actions in the same plan appear under `other_actions` and are not reverted.
- `approved_by` is whatever the approving client passed; it is not an authenticated identity.
