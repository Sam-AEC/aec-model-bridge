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
| `revit_place_views` and nine other tools | A view name or sheet number does not match exactly one view or sheet | Pick one of the candidates. See [View and sheet names](#view-and-sheet-names). |

A parameter name with no close match is not refused; the tool runs as before. An exact level name needs no question.

## View and sheet names

These tools name an existing view or sheet. Revit matches a view name or a sheet number character for character.

| Tool | Input |
| --- | --- |
| `revit_place_views` | `sheet` (sheet number), `views[].view_name` |
| `revit_make_sheet` | `views[].view_name` |
| `revit_set_view_templates` | `views[].view_name` |
| `revit_make_view_template` | `view.view_name` |
| `revit_align_crop` | `reference.view_name`, `views[].view_name` |
| `revit_add_revision_clouds` | `view.view_name` |
| `revit_make_schedule` | `sheet.number` |
| `revit_export` | `sheets[]` (sheet numbers) |
| `revit_issue_revision` | `sheets[]` (sheet numbers) |
| `revit_update_sheets` | `sheets[].number` |

All of them change the model or write files, so the check runs only when the call needs no approved plan and carries no `plan_id`: Auto mode or Dev mode. In Ask first mode the server does not read the names and does not change the arguments; the approved arguments run as drafted and Revit refuses a name that does not match exactly one view or sheet, as before.

When the check runs, the server lists views (with schedules) or sheets whose name or number contains the given text, with the read-only `revit_list_views_sheets_schedules`. If none does, it lists all of them and looks for a name inside the text or a close spelling.

- One view with exactly that name, or one sheet with exactly that number: no question.
- Several views with exactly that name: the choices are labelled `name [id N]`.
- Otherwise the candidates are views whose name, or sheets whose number or name, match ignoring case, contain the text, or are spelt close to it. A sheet is shown as `number - name`.
- At most 25 candidates are offered. The question and the refusal say "+N more" for the rest; call again with `view_id` or the exact sheet number to pick one of those.
- No candidate: no question and no refusal from the server; the tool runs and Revit refuses the name.
- The answer replaces that one input: a view becomes `view_id`, a sheet becomes its exact number. Each reference is one question, so a call with more than three unclear names ends with the plain refusal after three answers.
- When the list tool cannot run (mock mode, hidden by the tool profile, no Revit, an error), nothing is checked.

`sheet_set_qa_check` takes `sheet_numbers` too, but reports a number that is not in the snapshot as an error finding, so it does not ask. The view and sheet names in `providers/revit.py` (`view_name` of `revit_create_*_view`, `new_sheet_number` and `new_sheet_name`) name new views and sheets, so there is nothing to choose from. `snapshot_query` has no view or sheet filter.

`output_path` and `path` are no longer in the tool schemas' `required` lists, so a call without them reaches the server and gets the plain refusal or the question. They are still required to run.

## What elicitation is never used for

- Plan approval. Answers pass through the AI client, so they are not a person's approval. `elicit_choice` refuses to run for any approval tool (`plan_actions`, `execute_plan`, `approve_plan`, `reject_plan`, `rollback_plan`, `plan_revert`, `list_pending_plans`, `policy_show`, `get_proof_bundle`, and any tool whose name mentions plans, approval, rollback, revert, proof or policy), and when it is called from the approval code (`security/approval.py`, `security/dispatch.py`, `providers/approval_provider.py` and the other modules in `FORBIDDEN_CALLER_MODULES`). Tests check both guards and that those modules never mention elicitation. A person approves plans only in the Revit panel or with `aec-model-bridge-approve`.
- Secrets. A field name or question that looks like a password, token, key or credential is refused.
- Skipping the gate. After an answer the call runs again through the same approval gate, workspace path checks and audit as any other call.

## Client support

Client support for elicitation is UNVERIFIED. The tests use the MCP Python SDK in-memory client (`mcp` 1.30) with and without an elicitation callback. Whether Claude Desktop, Claude Code, Codex, Cursor or VS Code show the question has not been checked. A client that does not support it gets the plain refusal, as before. The view and sheet name check was tested with a fake list of views and sheets; against a live Revit it is UNVERIFIED.
