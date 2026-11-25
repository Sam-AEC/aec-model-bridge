# MCP token budget measurements

Measured 2026-11-05 with `MCP_REVIT_MODE=mock`, the supplied Python interpreter, a temporary workspace, no user modules or provider credentials, and no Revit model execution. Baseline captured at `87d1d1bb5312ccb9868786860cbc66f76c47b895` before production changes; results were reported before edits.

The checkout exposes **313** tools rather than the estimated 298. Sizes use SDK compact `ListToolsResult` / `CallToolResult` JSON (excluding JSON-RPC framing). Token estimates are characters / 4, not tokenizer counts or billed context. UTF-8 bytes, characters, inputs and per-tool data are retained in the JSON evidence files.

## Initial profile and response pass

*Dated: the 2026-11-05 measurements, before the 2026-11-16 metadata trims and compact reads; the follow-up sections below supersede these numbers.*

| Payload | Before characters | After characters | Before ~tokens | After ~tokens |
| --- | ---: | ---: | ---: | ---: |
| Full catalogue (302 tools) | 358,133 | 330,418 | 89,533 | 82,605 |
| Daily catalogue (231 tools) | 358,133 | 255,533 | 89,533 | 63,883 |
| Metadata enrichment, full catalogue | 132,722 | 105,007 | 33,181 | 26,252 |
| Module listing, full compact | 55,697 | 38,465 | 13,924 | 9,616 |
| Module listing, full compact IDs | 55,697 | 4,216 | 13,924 | 1,054 |
| Module listing, daily compact | 55,697 | 33,157 | 13,924 | 8,289 |
| Module listing, daily compact IDs | 55,697 | 3,793 | 13,924 | 948 |
| revit_list_elements, compact | 350 | 301 | 88 | 75 |
| revit_list_families, compact | 305 | 267 | 76 | 67 |
| revit_get_element_parameters, compact | 352 | 303 | 88 | 76 |
| revit_list_views, compact | 373 | 284 | 93 | 71 |
| plan_actions, compact | 1,058 | 768 | 265 | 192 |

Full catalogue savings: **7.74%**. Daily catalogue savings versus baseline: **28.65%**, hiding 71 tools. Module IDs projection with full profile saves **92.43%** of that response. The full profile retains all original tools. The five default read responses and default plan response are unchanged; response savings above require explicit opt-in formatting. The existing shared initialization approval instructions remain present and unchanged (excluded from catalogue totals).

## Follow-up: metadata trims (2026-11-16)

Same method (mock mode, chars / 4 over `list_tools`), measured on this branch. Tool counts are unchanged (302 full, 231 daily).

| Step | Full ~tokens | Daily ~tokens |
| --- | ---: | ---: |
| Before | 82,604 | 63,901 |
| Drop duplicate `annotations.title` (top-level `title` stays) | 80,114 | 61,970 |
| Short shared text for `dry_run`, `on_error`, `tag`, `limit`, `fields`, `status_labels`; `ids` item text dropped | 79,002 | 61,053 |
| One "Use X for A; use Y for B" sentence on 29 sibling tools | 79,688 | 61,740 |

Net: about 2,900 tokens fewer in full (3.5%) and 2,160 fewer in daily (3.4%). The sibling sentences add about 690 tokens on purpose, to help a model pick between near-duplicate tools. The shared parameter texts keep units, defaults and the rule that `dry_run` rolls back and writes nothing; only variants that said the same thing are replaced, tools with a different rule keep their own text. `plan_id` text and all approval wording are unchanged. The approval provider is now always visible, in every profile.

## Follow-up: compact reads, a size cap and paging (2026-11-16)

This changes what a read answer costs, not what the catalogue costs. The first pass above left default reads indented; that is no longer true for read-only tools.

- **Compact by default.** A tool with `readOnlyHint: true` returns minified JSON. `response_options.compact: false` brings back indented text. Tools that can write, and `plan_actions`, keep the old default (indented; compact only on request). Mock reads measured with the script below: `revit_list_elements` 260 to 221 characters, `revit_list_families` 221 to 191, `revit_get_element_parameters` 264 to 225, `revit_list_views` 276 to 200 (text content including the "executed successfully" line).
- **One size cap.** A read-only result over 20,000 characters (`DEFAULT_MAX_CHARS`) has its largest lists trimmed until it fits, stays valid JSON, and gets `truncated: true`, `total`, `returned`, `truncated_field` and a hint to narrow with limit/offset/count_only/fields or filters. `response_options.max_chars` sets another cap (0 = off). Short results, errors, running-job answers and every tool that is not read-only are never trimmed. In the mock catalogue `module_list_commands` (51,186 characters, full profile) now answers in 12,167; ask for `fields: ["modules.id", "modules.commands.id"]` or `max_chars: 0` to see more. `max_chars` is advertised on the five tools that already advertise `response_options`; any other read-only tool accepts `compact` and `max_chars` without listing them in its schema.
- **Never touched:** `plan_actions`, `execute_plan`, `list_pending_plans`, `get_proof_bundle`, `plan_revert`, the job tools and `revit_get_result`, and any result that carries `plan_id` or `plan_hash`. A test sends a 400-action plan (over 100,000 characters) through `call_tool` and checks the answer is byte-identical to the stored plan.
- **Paging.** `revit_list_elements`, `revit_list_views`, `revit_list_families`, `revit_get_categories`, `revit_get_warnings` and `revit_get_schedule_data` take optional `limit`, `offset` and `count_only`. The server slices the add-in's list after Revit answers (no add-in change), so Revit still builds the full list; only the answer is smaller. Without those arguments the result is unchanged except for the cap.

Catalogue cost of the new options (same method as above, mock mode): full 79,765 to 80,191 ~tokens (+0.5%), daily 61,799 to 62,225 (+0.7%); tool counts unchanged (302 and 231). The response savings above are separate from these totals and depend on what a live model returns.

## Follow-up: the `core` profile and a family map (2026-11-16)

Clients that load every tool pay for the whole catalogue on each session. Anthropic guidance says tool selection degrades past roughly 30-50 tools and that tool search pays off above about 10k tokens of definitions. `MCP_REVIT_TOOL_PROFILE=core` is a built-in profile that lists tools by name (not by provider or module ID) and keeps only the BIM-coordinator loop. The five approval tools stay visible in every profile, so core exposes 54 tools. Hidden tools are not listed and are refused at dispatch, in plan and job targets too, with a message that names `MCP_REVIT_TOOL_PROFILE=daily or full`.

Same method as above (mock mode, `scripts/measure_mcp_tokens.py`, chars / 4, over `list_tools`; `--profile core` is new). Re-measured on 2026-11-17 after including the three live reads required by the links and worksets audit on main 1.5.0 (compact reads, paging and size cap are in the tree); the catalogue totals match the paging row above to the token, because those changes add no tool text beyond it and the core profile only filters:

| Profile | Tools | ~Tokens before | ~Tokens after |
| --- | ---: | ---: | ---: |
| `full` | 302 | 80,191 | 80,191 |
| `daily` | 231 | 62,225 | 62,225 |
| `core` | 55 | not available | 14,151 |

Core is 82% smaller than full and 77% smaller than daily. It is still above 10k tokens, mostly the approval tools (about 1,000 for the first five; `policy_show` was added after these figures were measured), `revit_set_parameters`/`revit_get_parameters` (about 1,760) and the audits. Full and daily are unchanged, so no existing setup changes.

The family map is three lines in `SERVER_INSTRUCTIONS` (447 characters, about 112 tokens, sent once at initialisation, not part of the tool list). It names the prefixes and says a tool missing from the list is hidden by the startup profile and how to reach it (switch profile and restart). Instructions total 1,379 characters (about 345 tokens); the approval and Dev mode sentences are byte-for-byte unchanged and a test pins them. Core plus map is about 14,263 tokens.

What core keeps, and why (50 tools plus the approval tools):

| Family | Tools | Why |
| --- | ---: | --- |
| Context and results | 4 | `revit_get_context` (Dev flag, document), `revit_health`, `revit_get_document_info`, `revit_get_result` for async answers |
| Jobs | 2 | `job_status`, `job_cancel`: follow and stop a long run |
| Snapshots | 4 | `snapshot_take`, `snapshot_query`, `snapshot_diff`: the before/after evidence; `snapshot_compute`: one-call answers over a snapshot |
| QA checks and issues | 5 | `qaqc_checker_run_check`, `list_issues`, `resolve_issue`, `list_rules`, `list_rule_packs`: the issue loop (pack import/export/validate stay hidden) |
| Review and checks | 4 | `revit_review`, `revit_warnings_delta`, `revit_check_levels_grids`, `revit_system_report`: composite read-only verdicts |
| Module audits | 7 | naming, doors and rooms, sheets and views, warnings triage, model bloat, links and worksets, `revit_cleanup_audit`: the routine coordinator audits |
| Element and project reads | 11 | list/inspect elements, element parameters, geometry, levels, views, families, categories, Revit links, link instances and worksets |
| Warnings and documents | 2 | `revit_get_warnings`, `revit_list_views_sheets_schedules` |
| Model inspector | 2 | summarize a model, inspect the selection |
| Parameters | 3 | `revit_get_parameters`, `revit_set_parameters` (the approved write path), `parameter_manager_filter_params` |
| Selection | 4 | get/set selection, select by unique ids, select by query: hand findings to the person in Revit |
| Power tools | 2 | `revit_execute_python` (anything not listed, still behind approval), `revit_api_lookup` (check an API before scripting) |

Left out on purpose: single-purpose creators (walls, sheets, views, MEP, sparing), exports, recipes, family editing, revisions, Rhino, Speckle, Navisworks, IFC and rule-pack admin. Reach them with `daily` or `full`. A user custom profile file can still narrow `core` but cannot hide approval tools.

Reproduce: `python scripts/measure_mcp_tokens.py --profile core --output docs/mcp-token-measurement-after-core.json`. The command writes the evidence file. Measurement files are not kept in the repository.

## Follow-up: output schemas

Twenty read tools advertise an MCP `outputSchema` (`src/revit_mcp_server/output_schemas.py`). Each schema lists only the main top-level keys and their types, so it stays small. Same method as above (mock mode, `scripts/measure_mcp_tokens.py`, chars / 4 over `list_tools`), measured with and without the schemas on the same tree:

| Profile | Tools | Characters without | Characters with | ~Tokens without | ~Tokens with |
| --- | ---: | ---: | ---: | ---: | ---: |
| `full` | 311 | 332,323 | 336,308 | 83,081 | 84,077 |
| `daily` | 240 | 260,460 | 264,445 | 65,115 | 66,111 |
| `core` | 57 | 59,612 | 63,522 | 14,903 | 15,881 |

The schemas add about 1,000 tokens in every profile (1.2% of full, 6.6% of core); 19 of the 20 tools are visible in `core` (all but `module_list_commands`). A successful call to one of these tools now carries its result twice: as text (unchanged) and as `structuredContent`. A client that passes only one of them to the model sees no change in response cost.
## Follow-up: deferred loading and the always-loaded set

A client with tool search can defer this server and keep a short always-loaded set: `ALWAYS_LOADED_TOOLS` in `tool_profiles.py` (`revit_get_context`, `snapshot_take`, `snapshot_compute`, `search_tools`, `context_report`, `plan_actions`, `execute_plan`, `list_pending_plans`). Setup: [deferred tool loading](deferred-tool-loading.md).

Same method as above (mock mode, chars / 4 over `list_tools`), with 312 tools, after `context_report` and the `_meta` always-load flag were added. `--always-loaded` measures only the always-loaded set. Names-only is the JSON list of tool names.

| Setup | Tools in prompt | ~Tokens of tool definitions |
| --- | ---: | ---: |
| `full`, no deferral | 312 | 83,278 |
| `daily`, no deferral | 241 | 65,312 |
| `core`, no deferral | 58 | 15,094 |
| Always-loaded set only (any profile) | 8 | 1,832 |
| `full` deferred, plus names of the 304 deferred tools | 8 + 304 names | about 3,740 |

With the Claude API tool search tool, deferred definitions are not in the prompt until a search returns them, so the startup cost is the always-loaded row plus the search tool itself. Claude Code lists the names of deferred tools at session start; the last row estimates that from names-only JSON (7,772 characters for all 312 names) and is not a measurement of Claude Code's own prompt. Neither row was measured in a live client. Server instructions (about 345 tokens) are sent in every setup.

Reproduce: `python scripts/measure_mcp_tokens.py --always-loaded --output always-loaded.json`, and `--profile full|daily|core` for the other rows. `--only-tools a,b,c` measures any other subset.

## Follow-up: the `learned` profile

`MCP_REVIT_TOOL_PROFILE=learned` lists `core`, the always-loaded set and the 25 most used tools of the last 30 days from local usage counts, so a list fits what one person actually calls. It falls back to `daily` with fewer than 50 counted calls. `context_report` shows the most used tools and suggests `learned` when it would list at most 75% of the current list. Details and privacy: [learned profile](learned-profile.md).

## What dominates?

*Dated: 2026-11-05. The `module_list_commands` size below is from before the 2026-11-16 trims; see the follow-up sections above.*

Names-only JSON costs 7,538 characters (~1,885 tokens), versus 358,133 characters (~89,533 tokens) for the full schemas. Metadata originally adds 132,722 UTF-8 bytes (~33,181 tokens) over raw provider Tool definitions.

The assertion that plan echoes and results burn more than names is **partly confirmed**: `module_list_commands` alone costs ~13,924 tokens, exceeding every tool name combined (~1,885). The measured small parameter plan (~265 tokens) and four mock model reads (~76-93 tokens each) do not. The full schema catalogue dominates all these samples. No inference about real model result sizes or long script echoes is justified by these canned responses.

The sample plan request is 136 characters with one `revit_set_parameter_value` action, a 16-character value, and zero script characters. It creates a pending plan only. No approval or execution is performed. Its 590-character compact data payload expands to a 1,058-character serialized default response. The real module catalogue payload expands from 35,367 compact data characters to 55,697 serialized response characters.

The first probe also sampled health (197 response characters), document info (313), selection (305), one parameter value (385), and context (506). The definitive five-read benchmark below uses module commands, elements, families, element parameters, and views.

## Follow-up: large script-plan echoes

A second measurement, taken before the follow-up code changes, creates a pending
plan with a 16,384-character comment-only Python script. It never approves or
executes the plan. The script is echoed twice in the default plan structure:
`actions[].arguments.script` and `actions[].diff.after.script`.

| Payload | Before characters | After characters | Before ~tokens | After ~tokens |
| --- | ---: | ---: | ---: | ---: |
| Compact script-plan response | 33,412 | 795 | 8,353 | 199 |
| Daily catalogue including the new option | 255,533 | 255,733 | 63,883 | 63,933 |

Request `response_options: {"compact": true, "omit_action_arguments": true}`
on `plan_actions` to omit these argument echoes from its returned summary.
This saves **97.62%** of the measured response, with a 50-token schema cost per
catalogue. The original script input cost remains. Default responses, stored
arguments, before evidence, complete review, plan hash and human approval rules
are preserved. The summary explicitly directs human review to the complete
stored plan; its hash identifies that full plan. Distinct after-state data,
errors and running-result diagnostics remain visible. This option does not
enable arbitrary plan field selection.

Evidence: `mcp-token-measurement-plan-script-before.json` (script fixture) and `mcp-token-measurement-plan-script-after.json` (same fixture with argument omission). The commands under Reproduce write them; they are not kept in the repository.

## Baseline by provider

Each row counts its own tool array. Array wrappers mean row sums differ slightly from the single catalogue wrapper.

| Provider | Tools | Characters | UTF-8 bytes | ~tokens |
| --- | ---: | ---: | ---: | ---: |
| approval | 5 | 3,588 | 3,588 | 897 |
| exporter | 3 | 2,548 | 2,548 | 637 |
| graph | 7 | 5,346 | 5,346 | 1,336 |
| ifc | 7 | 3,800 | 3,800 | 950 |
| jobs | 2 | 875 | 875 | 219 |
| mapper | 3 | 2,177 | 2,177 | 544 |
| module | 108 | 201,392 | 201,394 | 50,348 |
| navisworks | 15 | 10,143 | 10,143 | 2,536 |
| revit | 110 | 94,519 | 94,519 | 23,630 |
| revit_jobs | 3 | 2,798 | 2,798 | 700 |
| rhino | 19 | 16,184 | 16,184 | 4,046 |
| semantic | 3 | 2,412 | 2,412 | 603 |
| speckle | 17 | 12,483 | 12,483 | 3,121 |

## Baseline manifest modules

These rows break down the `module` provider above; they are not additional tools. Native duct/pipe tools were owned by the Revit provider in the baseline and now have explicit `revit_mep` membership.

| Module | Tools | Characters | UTF-8 bytes | ~tokens |
| --- | ---: | ---: | ---: | ---: |
| bcf_exchange | 2 | 1,817 | 1,817 | 454 |
| clash_triage | 2 | 1,728 | 1,728 | 432 |
| familytype_mapper | 2 | 1,234 | 1,234 | 308 |
| hello_world | 1 | 460 | 460 | 115 |
| links_worksets_audit | 1 | 1,687 | 1,687 | 422 |
| model_bloat | 1 | 1,042 | 1,042 | 260 |
| model_changes | 2 | 1,425 | 1,425 | 356 |
| model_inspector | 7 | 3,696 | 3,696 | 924 |
| naming_checker | 2 | 2,213 | 2,213 | 553 |
| parameter_manager | 5 | 4,180 | 4,182 | 1,045 |
| pyrevit_bridge | 3 | 2,273 | 2,273 | 568 |
| qaqc_checker | 8 | 5,024 | 5,024 | 1,256 |
| recipe_runner | 4 | 1,884 | 1,884 | 471 |
| report_generator | 3 | 2,580 | 2,580 | 645 |
| revit | 11 | 28,408 | 28,408 | 7,102 |
| revit_api | 1 | 2,034 | 2,034 | 508 |
| revit_cleanup | 1 | 3,283 | 3,283 | 821 |
| revit_docs | 17 | 43,935 | 43,935 | 10,984 |
| revit_family | 1 | 4,780 | 4,780 | 1,195 |
| revit_ifc | 1 | 3,172 | 3,172 | 793 |
| revit_mep | 6 | 31,166 | 31,166 | 7,792 |
| revit_params | 2 | 7,423 | 7,423 | 1,856 |
| revit_recipes | 5 | 7,101 | 7,101 | 1,775 |
| revit_sparing | 8 | 29,324 | 29,324 | 7,331 |
| schedule_consistency | 1 | 1,211 | 1,211 | 303 |
| selection_tools | 8 | 6,321 | 6,321 | 1,580 |
| sheet_view_audit | 1 | 772 | 772 | 193 |
| warnings_triage | 1 | 1,143 | 1,143 | 286 |

## Fifteen largest baseline tools

| Tool | Characters | UTF-8 bytes | ~tokens |
| --- | ---: | ---: | ---: |
| revit_mep_route | 8,379 | 8,379 | 2,095 |
| revit_mep_hanger_place | 7,780 | 7,780 | 1,945 |
| revit_sparing_place | 6,271 | 6,271 | 1,568 |
| revit_mep_connect | 5,222 | 5,222 | 1,306 |
| revit_make_family | 4,768 | 4,768 | 1,192 |
| revit_mep_hanger_plan | 4,725 | 4,725 | 1,181 |
| revit_sparing_place_spec | 4,491 | 4,491 | 1,123 |
| revit_make_view | 4,345 | 4,345 | 1,086 |
| revit_set_parameters | 4,303 | 4,303 | 1,076 |
| revit_make_schedule | 4,274 | 4,274 | 1,068 |
| revit_place_views | 4,013 | 4,013 | 1,003 |
| revit_sparing_find | 3,684 | 3,684 | 921 |
| revit_add_revision_clouds | 3,653 | 3,653 | 913 |
| revit_sparing_status_set | 3,615 | 3,615 | 904 |
| revit_sparing_export_spec | 3,547 | 3,547 | 887 |

## Daily dependency audit

An offline search of the owner's own Dynamo automation scripts found no calls to the tools the daily profile hides. The calls they do make (context, Python, result collection, pending-plan creation and plan execution) remain available. The owner chose to retain used modules if discovered; this audit required no exceptions.

Profiles select provider/manifest IDs, including aliased commands. Native duct/pipe declarations carry explicit `revit_mep` ownership. Hidden direct calls, nested module calls and job targets are refused. Existing approved plans are preflighted before claiming any action; profile refusal preserves their approved state. The panel remains unrestricted and all exposed writes still require the existing approval process.

## Validation

*Dated: the 2026-11-05 implementation run.*

Initial implementation package suite: **2,747 passed, 150 skipped** in 190.28 seconds using
a project virtual environment. The two wheel-build tests
skip because `build` is not installed; browser, live-Revit and platform-specific
checks account for the other skips. No live Revit writes were performed.
Ruff passes on all changed Python files; `git diff --check` passes.
New coverage includes static full/daily/custom discovery, file/glob validation,
alias ownership, hidden direct and nested calls, untouched blocked approved
plans, human-only approval rules, redaction, default response compatibility,
opt-in projection/minification, and daily/custom subprocess MCP round trips.
The follow-up argument-echo change passes **109 targeted tests**, including
approval/review/hash invariants, default-response compatibility, invalid options,
error/progress preservation, and real MCP subprocess round trips. All changed
Python files pass Ruff. Independent review found no remaining concrete defects.

## Reproduce

```powershell
& python scripts/measure_mcp_tokens.py --profile full --output docs/mcp-token-measurement-after-full.json
& python scripts/measure_mcp_tokens.py --profile full --compact-read-results --project-module-commands --output docs/mcp-token-measurement-after-compact.json
& python scripts/measure_mcp_tokens.py --profile daily --compact-read-results --project-module-commands --output docs/mcp-token-measurement-after-daily.json
& python scripts/measure_mcp_tokens.py --profile daily --compact-read-results --plan-script-chars 16384 --omit-plan-arguments --output docs/mcp-token-measurement-plan-script-after.json
```

To reproduce the original baseline, run the initial measurement script against the original source commit. Optional `--profile-file` accepts a custom include/exclude file. Each run records its Git HEAD and settings; after snapshots were captured on the working tree during implementation.

Evidence: the JSON files the commands above write (before, after full, after compact, after daily). They are not kept in the repository; earlier copies are in the commit history.
