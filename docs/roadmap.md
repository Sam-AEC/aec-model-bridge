# Adoption priorities for BIM coordinators

Prepared 2026-10-09. These are proposed priorities, not shipped-feature or
traction claims. The initial audience is BIM coordinators who need to find
missing model data and approve parameter fixes.

The first useful result is a repeatable **find missing parameters → review
exact changes → approve → verify** workflow on a synthetic model in a real
Revit session. Missing door Marks are the smallest first case; inconsistent
values follow once coordinator rules and expected values are explicit. Existing
QA rules, parameter planning and the approval gate provide the foundation.
Effort labels below are relative estimates, not delivery dates.

| Priority | Deliverable and rationale | Effort | Verification criteria |
| --- | --- | --- | --- |
| 0 | Require explicit real snapshots in the live QA and parameter workflow, and fail clearly when one is absent. Today these modules generate mock data when `snapshot_id` is omitted, even if Revit is connected. Removing that ambiguity is a prerequisite for a credible demo and reliable model fixes. | Small to medium | The live path rejects absent snapshots with an actionable instruction, validates the snapshot document identity, and identifies its source/time in findings and previews. Explicit mock mode remains labelled. The after check uses a newly captured snapshot of the same document; synthetic snapshot data cannot be presented as a live result. |
| 1 | A short real Revit demo and repeatable runbook. Show missing door Marks, select affected elements, review proposed values, approve once and rerun the check. This makes the existing product understandable and provides evidence of a complete coordinator task. | Small, with live Revit access | Rebuild the fixture and obtain the same rule counts on two runs. Before the door fix, the intended baseline is 12 missing Marks and 3 missing room Numbers; after it, 0 missing Marks and 3 unchanged room findings. Capture actual counts, Revit version, commit and before/after evidence. A rejected plan must leave parameters unchanged. Publish a recording only after the live result is verified. |
| 2 | Make the parameter fix review dependable. Use explicit element IDs, parameter names, old/new values, warnings and skipped elements; use user-confirmed numbering rules. Coordinators need to know exactly which model data will change and why. | Medium | Only selected missing values change. Existing populated Marks remain intact. Read-only or owned elements surface actionable failures/skips. A fresh read checks final values and reruns QA; failed or partial execution cannot appear as a completed fix. Cover stale-document/changed-value handling and document the supported rollback path. |
| 3 | An install-to-first-check diagnostic path. Explain the Revit version, add-in connection, active document, hub/client state and next action in one place. The source/install instructions currently require several components, so reducing setup failures helps new users reach the demo. | Small to medium | A fresh Windows account installs one supported Revit package and completes the read-only check without source editing. Missing Python, wrong Revit package, stopped bridge and no open document each produce a specific recovery step. Test each advertised Revit version before claiming equivalent live support. |
| 4 | A compact QA and change report that coordinators can hand over. Include document identity, rule pack, affected elements, before/after values, approval outcome and verification result. This makes the workflow useful in project reviews after the chat closes. | Small to medium | Report links every fix to its plan and element identity, distinguishes unresolved findings/skips/failures, and uses fresh model data for the after state. Reopening the report must not require an AI account. Measure time saved against the same manual check with actual pilot users. |

## First demo scope

The snapshot contract needs repair first. The add-in used to write
`snapshots/snapshot-{GUID}.json` while returning a bare GUID, and the Python
modules load `snapshots/{snapshot_id}.json`; the add-in now writes
`snapshots/{GUID}.json` (compile and verify against live Revit before relying
on it). The add-in also uses its own workspace environment, which can differ
from the Python server's workspace. Confirm the workspace matches, and verify the
snapshot covers the categories required by the QA rules. Never silently replace
a failed live extraction with generated mock data.

Use a disposable copy of the [canonical model](../fixtures/canonical-model/README.md).
The [seeded defect manifest](../fixtures/canonical-model/seeded-defects.json)
specifies 12 doors without Mark and 3 rooms without Number. These are expected
fixture counts, not a claim that a live run has already passed. The first
recording fixes only the door Marks, using an explicit unique numbering pattern
reviewed by the coordinator. Preserve the room findings to show the scope of
the approved change.

Capture a real snapshot from that open synthetic Revit document and pass its
explicit `snapshot_id` to every QA and parameter call. Record document identity
and source/time. Capture a new snapshot after execution for verification. An
omitted snapshot currently falls back to generated mock data in both modules;
connected Revit alone does not establish that findings describe the open model.
Complete priority 0 before treating the product's default workflow as live.

Record the check result, affected element selection, parameter preview, human
approval, execution result and a fresh check. Include a rejected-plan run and
the unchanged before/after values in the verification record. Exercise the
same commands through a real MCP client; a UI mockup or canned mock-mode
response cannot establish live Revit behavior.

Capture a short clip after that sequence works and store a text runbook beside
it with the commit, Revit version, fixture generation command, prompts/tool
calls and expected counts. Use small targeted tests for any newly fixed
behavior, then the existing live e2e path where applicable:

```powershell
# Requires Revit with the add-in loaded; use a disposable fixture project.
python scripts\revit\generate_canonical_test_model.py
$env:AEC_MODEL_BRIDGE_E2E = '1'
python -m pytest packages\mcp-server-revit\tests\e2e -m e2e
```

Do not assume this existing e2e suite alone covers the full review/approve/fix
demo; record missing coverage and verify the full sequence in the live client.

## Evidence and sequencing

- [Core QA rule pack](../packages/mcp-server-revit/src/revit_mcp_server/modules/qaqc_checker/rules/core.yaml) already contains `door_missing_mark` and `room_missing_number`; [the checker](../packages/mcp-server-revit/src/revit_mcp_server/modules/qaqc_checker/module.py) tracks findings in a workspace SQLite store.
- The checker's `_get_data` and the [parameter manager's](../packages/mcp-server-revit/src/revit_mcp_server/modules/parameter_manager/module.py) `_get_elements` call `generate_mock_snapshot()` when `snapshot_id` is empty. This observed fallback motivates priority 0; it is a proposed fix, not a claim that it has been implemented.
- [Parameter manager](../packages/mcp-server-revit/src/revit_mcp_server/modules/parameter_manager/module.py) already produces planned changes with before values, validation errors and worksharing warnings. Validate those warnings against real Revit ownership before promising batch safety.
- [Approval lifecycle](0008-approval-gate-lifecycle.md) and [native chat trust model](0012-native-agent-chat-backend.md) describe the human approval boundary. Acceptance criteria must verify the concrete client path used in the demo.
- [Installation](install.md) documents the Python server and native add-in requirements; [audit logging](logging-and-audit.md) explains the two log layers needed to correlate a requested change with actual Revit execution.

Complete the first demo before expanding the integration surface. Decide the
next workflow from observed coordinator setup failures and repeated QA tasks.
Keep Navisworks, Power BI and broader provider work behind this measured adoption
loop unless a real pilot makes one of them a blocker.

The [pilot validation plan](pilot-validation-plan.md) describes how to test the
safety, interop and client-reach assumptions with five non-scripting BIM
coordinators. No pilot has been run.
