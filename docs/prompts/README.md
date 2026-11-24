# Prompt library

Copy-ready prompts for BIM coordinators, BIM managers and computational designers who use an AI client with AEC Model Bridge. Each prompt names the tools it should lead to. Reads run freely. Every model change ends in a plan that a person approves in the Revit panel or with `aec-model-bridge-approve`.

The server also ships five MCP prompts (`qa_review`, `parameter_fix`, `sheet_prep`, `handover_report`, `first_run`); see [clients](../clients.md#prompts-and-resources). This library is longer and covers more tasks. Paste a prompt into the chat; nothing here is registered with the server.

## Files

| File | Prompts | Covers |
| --- | --- | --- |
| [model-qa-and-health.md](model-qa-and-health.md) | 8 | First look, warnings, rule packs, health score, bloat, links and worksets, levels and grids, change tracking |
| [parameters-and-data.md](parameters-and-data.md) | 8 | Completeness, bulk fill, Excel round trip, duplicate Marks, shared parameters, schedules, revert, quantities |
| [sheets-and-documentation.md](sheets-and-documentation.md) | 8 | Pre-issue audit, naming, sheets from CSV, renumbering, view placement, revisions, title blocks, PDF export |
| [views-and-annotation.md](views-and-annotation.md) | 5 | View templates, crop alignment, tagging, review views, blank-view check |
| [coordination-and-clashes.md](coordination-and-clashes.md) | 5 | Category clashes, measured overlaps, Navisworks clash triage, MEP open ends, joins and openings |
| [ifc-bcf-exchange.md](ifc-bcf-exchange.md) | 5 | IFC inspection, IDS checks, IFC export check, BCF export and import |
| [handover.md](handover.md) | 4 | QA hand-over report, Excel review pack, asset data completeness, change record |
| [scripting-execute-python.md](scripting-execute-python.md) | 5 | Read-only scripts, API lookup, write scripts under a plan, debugging, pyRevit scripts |
| [dynamo.md](dynamo.md) | 5 | Porting Dynamo Python nodes, checking graph results, data for graphs, Player scripts as recipes |
| [revit-agent-preflight-and-verify.md](revit-agent-preflight-and-verify.md) | 1 | Long system prompt for agents that build in live Revit |

## How to use a prompt

1. Pick a prompt. Replace every `{placeholder}` with your value. Leave optional parts out rather than guessing.
2. Paste it into your MCP client (Claude Desktop, Claude Code, Codex, Cursor, VS Code and others; see [install](../install.md)).
3. Read what the assistant reports. It should name the document, the scope and the counts before it proposes anything.
4. For a change, review the plan in the Revit panel (Plans view). Approve, or reject and say what to change.
5. Ask the assistant to read the result back. A prompt is finished when the read-back matches the plan.

Set `MCP_REVIT_MODE=mock` to try any prompt with sample data and no Revit. Mock results are sample data, not your model.

## How prompts map to the approval flow

Every prompt follows the same order:

| Step | What the assistant does | Tools (examples) |
| --- | --- | --- |
| Inspect | Confirms the document and reads what it needs. No approval needed. | `revit_get_context`, `snapshot_take`, `revit_get_parameters` |
| Propose | Drafts a plan with exact tool arguments and a short review text. | `parameter_manager_plan_set_params`, `plan_actions` |
| Approve | A person approves in the Revit panel or with `aec-model-bridge-approve`. The assistant cannot approve, and approval tools are not offered to AI clients. | none |
| Execute | Runs the approved plan once, with exactly the approved arguments. | `execute_plan` |
| Verify | Reads the result back and reports what changed and what did not. | `snapshot_diff`, `get_proof_bundle` |
| Undo (if needed) | Drafts a revert plan from the proof bundle; it is approved like any other plan. | `plan_revert` |

Rules every prompt keeps:

- A write tool called without an approved plan is refused. In mock mode the refusal is the same as in live mode.
- `dry_run` on a write tool still needs an approved plan (observed in mock mode). Use read tools to preview instead.
- `revit_execute_python` with `mode` "read" needs no approval and cannot open transactions. With `mode` "write" it needs an approved plan.
- File outputs (PDF, IFC, BCF, Excel) do not change the model, but a file export through `revit_export` still goes through a plan. Files are written inside the workspace only.
- If the panel shows Dev mode or a timed Auto window, per-change approval is off. Switch it off for these prompts.

## Placeholders

- `{level}`: a level name as it appears in Revit, for example `Level 02`.
- `{category}`: a Revit category name, for example `Doors`, `Walls`, `Mechanical Equipment`.
- `{parameter}` and `{value}`: a parameter name and the value to set.
- `{snapshot_id}`: an id returned by `snapshot_take`. Most module tools need one; pass it rather than relying on a default.
- `{file}`: a file name inside the workspace folder.

## Test status

Each prompt has a **Tested** line:

- **Mock: exercised** means the listed tool sequence was called in `MCP_REVIT_MODE=mock` and returned without an error, or a write stopped at the approval gate as expected. The prompt text itself was not run through an AI client, and mock data says nothing about a real model.
- **Untested** means the tool sequence was not called in mock mode, usually because it needs live Revit, Navisworks or an approved plan.

No prompt here has a verified live-Revit result. Treat live behaviour as UNVERIFIED (see [release checklist](../release-checklist.md)).

## Sources

The prompt set draws on these sources. Pages were found by web search; some could not be fetched from the build environment, so claims are limited to what the search summaries showed.

- MCP prompts specification (user-controlled prompts, declared arguments, argument validation): https://modelcontextprotocol.io/specification/2025-11-25/server/prompts
- Anthropic prompting best practices (be clear and direct, examples, XML tags): https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/be-clear-and-direct
- OpenAI prompt engineering best practices (instructions first, specific format, examples): https://help.openai.com/en/articles/6654000
- Autodesk Revit API forum, "CHATgpt to help with scripts" (useful for simple API tasks and refactoring): https://forums.autodesk.com/t5/revit-api-forum/chatgpt-to-help-with-scripts/m-p/11730013
- Autodesk Revit Architecture forum, "Integrating ChatGPT with Revit": https://forums.autodesk.com/t5/revit-architecture-forum/integrating-chatgpt-with-revit/m-p/12415371
- Autodesk University, "Conversational BIM: From Prompts to Projects" (2025): https://www.autodesk.com/autodesk-university/class/Conversational-BIM-From-Prompts-to-Projects-2025
- Autodesk University, "AI-Ready BIM Foundation: Push-Button Cross-Discipline Automation with Revit MCP, Dynamo and pyRevit" (2026): https://www.autodesk.com/autodesk-university/class/AI-Ready-BIM-Foundation-Push-Button-Cross-Discipline-Automation-with-Revit-MCP-Dynamo-and-pyRevit-2026
- Autodesk University, "Design Requirements Verification with BIM Automation and AI Agents" (2026): https://www.autodesk.com/autodesk-university/class/Design-Requirements-Verification-with-BIM-Automation-and-AI-Agents-2026
- Autodesk Validation Tool documentation (model checks against project standards): https://help.autodesk.com/view/VTDOCS/ENU/
- Archgyan, "ChatGPT prompts for architects" (BIM coordination prompts; specific, contextual prompts work better): https://archgyan.com/chatgpt-prompts-for-architects
- Imaginit, "Chat GPT for Revit use" (scripts generated for Dynamo): https://resources.imaginit.com/building-solutions-blog/chat-gpt-for-revit-use
- Dynamo Python Primer (UnwrapElement, transactions): https://dynamopythonprimer.gitbook.io/dynamo-python-primer/4-revit-specific-topics/working-with-transactions
- Dynamo Primer, graph strategies: https://primer2.dynamobim.org/9_best_practices/1-graph-strategies

The Dynamo forum (forum.dynamobim.com) was searched but no thread was returned by the search tool, so no forum thread is cited.

## Contribute a prompt

1. Add it to the themed file it fits, with the next free id (for example `QA-09`).
2. Use the same fields: When to use, Prompt, Tools, Expected result, Safety (for anything that writes), Tested.
3. Name real tools only. Check names with `search_tools` or [the tool catalog](../tools-generated.md). Write tool names on the **Tools** line in backticks.
4. A prompt that changes the model must say that the assistant drafts a plan, that it cannot approve, and that it waits for the person. Never tell the assistant to approve a plan, and never name a human-only tool such as the approve, reject or rollback tools.
5. Mark it **Untested** unless you ran the tool sequence in mock mode. Do not claim live results.
6. Update the count in the table above and run `uv run pytest -q tests/test_prompt_library.py` from `packages/mcp-server-revit`. The test checks every tool name against the registry.
