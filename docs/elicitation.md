# Elicitation: questions for missing or ambiguous inputs

MCP elicitation lets a server ask the person at the client one short, structured question (`elicitation/create`, form mode). AEC Model Bridge uses it for a small set of missing or ambiguous inputs instead of guessing. The code is in `packages/mcp-server-revit/src/revit_mcp_server/elicitation.py`.

## When the server asks

The server asks only when all of these hold:

- The client declared the `elicitation` capability (form mode) when it connected.
- The tool raised `InputNeeded` for one of the cases below.
- The tool is not an approval tool, and the call carries no `plan_id`.
- The call does not need an approved plan. In Ask first mode a gated tool never asks, because an answer changes the arguments and could not match an approved action. In Auto or Dev mode it may ask.

In every other case, and when the person declines, cancels, does not answer within 120 seconds or gives an answer outside the offered choices, the call ends with the plain refusal: an error of kind `input_needed` that names the missing input and the choices. The AI client can then call again with the input set.

One call asks at most three questions, one input at a time. Each question has one field: a choice from a list (`enum`) or a short text.

## Cases

| Tool | Input | Question |
| --- | --- | --- |
| `snapshot_query` | `filter.level` (a level name) matches several levels, or none exactly | Pick one level from the matching names (or every level when none is close). The answer becomes `filter.level_uid`. |
| `snapshot_query` | `filter.parameter.name` is on no element or type in the snapshot, and close names exist | Pick one of the close names. |
| `snapshot_compute` | A field path such as `params.Fire Rating` names a parameter that no element or type has, and close names exist. The name is the one segment after `params.`; a suffix such as `.v` or `.storage` is not part of it | Pick one of the close names. Every path that names it is changed, and a suffix is kept. A saved query then runs inline with the changed steps. |
| `revit_export_dwg`, `revit_export_ifc`, `revit_export_navisworks`, `revit_export_image` | `output_path` is missing | Type a file name. The file goes in the workspace folder with the tool's extension. |
| `revit_export` | `path` is missing (and `format` is valid) | Type a file name. The file goes in the workspace folder with the format's extension. |

A parameter name with no close match is not refused; the tool runs as before. An exact level name needs no question.

`output_path` and `path` are no longer in the tool schemas' `required` lists, so a call without them reaches the server and gets the plain refusal or the question. They are still required to run.

## What elicitation is never used for

- Plan approval. Answers pass through the AI client, so they are not a person's approval. `elicit_choice` refuses to run for any approval tool (`plan_actions`, `execute_plan`, `approve_plan`, `reject_plan`, `rollback_plan`, `plan_revert`, `list_pending_plans`, `policy_show`, `get_proof_bundle`, and any tool whose name mentions plans, approval, rollback, revert, proof or policy), and when it is called from the approval code (`security/approval.py`, `security/dispatch.py`, `providers/approval_provider.py` and the other modules in `FORBIDDEN_CALLER_MODULES`). Tests check both guards and that those modules never mention elicitation. A person approves plans only in the Revit panel or with `aec-model-bridge-approve`.
- Secrets. A field name or question that looks like a password, token, key or credential is refused.
- Skipping the gate. After an answer the call runs again through the same approval gate, workspace path checks and audit as any other call.

## Client support

Client support for elicitation is UNVERIFIED. The tests use the MCP Python SDK in-memory client (`mcp` 1.30) with and without an elicitation callback. Whether Claude Desktop, Claude Code, Codex, Cursor or VS Code show the question has not been checked. A client that does not support it gets the plain refusal, as before.
