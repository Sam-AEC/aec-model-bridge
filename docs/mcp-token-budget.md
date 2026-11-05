# MCP token budget measurements

Measured 2026-11-05 with `MCP_REVIT_MODE=mock`, the supplied Python interpreter, a temporary workspace, no user modules or provider credentials, and no Revit model execution. Baseline captured at `87d1d1bb5312ccb9868786860cbc66f76c47b895` before production changes; results were reported before edits.

The checkout exposes **302** tools rather than the estimated 298. Sizes use SDK compact `ListToolsResult` / `CallToolResult` JSON (excluding JSON-RPC framing). Token estimates are characters / 4, not tokenizer counts or billed context. UTF-8 bytes, characters, inputs and per-tool data are retained in the JSON evidence files.

## Before and after

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

## What dominates?

Names-only JSON costs 7,538 characters (~1,885 tokens), versus 358,133 characters (~89,533 tokens) for the full schemas. Metadata originally adds 132,722 UTF-8 bytes (~33,181 tokens) over raw provider Tool definitions.

The assertion that plan echoes and results burn more than names is **partly confirmed**: `module_list_commands` alone costs ~13,924 tokens, exceeding every tool name combined (~1,885). The measured small parameter plan (~265 tokens) and four mock model reads (~76-93 tokens each) do not. The full schema catalogue dominates all these samples. No inference about real model result sizes or long script echoes is justified by these canned responses.

The sample plan request is 136 characters with one `revit_set_parameter_value` action, a 16-character value, and zero script characters. It creates a pending plan only. No approval or execution is performed. Its 590-character compact data payload expands to a 1,058-character serialized default response. The real module catalogue payload expands from 35,367 compact data characters to 55,697 serialized response characters.

The first probe also sampled health (197 response characters), document info (313), selection (305), one parameter value (385), and context (506). The definitive five-read benchmark below uses module commands, elements, families, element parameters, and views.

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

Searched sibling `dynamoscript14` offline, including hidden files and embedded `.dyn` content while excluding `.git`, dependency folders and logs. No references to proposed hidden tools were found. Actual calls in `roadmap-automsereing/common/mcp_session.py`: context (line 175), Python (178), result collection (185), pending-plan creation (190), plan execution (192). Those remain available. IFC mentions in local helpers use `ifcopenshell` or direct Revit APIs and are not hidden MCP calls. The owner chose to retain used modules if discovered; this audit required no exceptions.

Profiles select provider/manifest IDs, including aliased commands. Native duct/pipe declarations carry explicit `revit_mep` ownership. Hidden direct calls, nested module calls and job targets are refused. Existing approved plans are preflighted before claiming any action; profile refusal preserves their approved state. The panel remains unrestricted and all exposed writes still require the existing approval process.

## Validation

Final package suite: **2,747 passed, 150 skipped** in 190.28 seconds using
`C:/Users/samo3/.aec-tools/venv/Scripts/python.exe`. The two wheel-build tests
skip because `build` is not installed; browser, live-Revit and platform-specific
checks account for the other skips. No live Revit writes were performed.
Ruff passes on all changed Python files; `git diff --check` passes.
New coverage includes static full/daily/custom discovery, file/glob validation,
alias ownership, hidden direct and nested calls, untouched blocked approved
plans, human-only approval rules, redaction, default response compatibility,
opt-in projection/minification, and daily/custom subprocess MCP round trips.

## Reproduce

```powershell
& C:/Users/samo3/.aec-tools/venv/Scripts/python.exe scripts/measure_mcp_tokens.py --profile full --output docs/mcp-token-measurement-after-full.json
& C:/Users/samo3/.aec-tools/venv/Scripts/python.exe scripts/measure_mcp_tokens.py --profile full --compact-read-results --project-module-commands --output docs/mcp-token-measurement-after-compact.json
& C:/Users/samo3/.aec-tools/venv/Scripts/python.exe scripts/measure_mcp_tokens.py --profile daily --compact-read-results --project-module-commands --output docs/mcp-token-measurement-after-daily.json
```

To reproduce the original baseline, run the initial measurement script against the original source commit. Do not overwrite the preserved before artifact. Optional `--profile-file` accepts a custom include/exclude file. Each run records its Git HEAD and settings; after snapshots were captured on the working tree during implementation.

Evidence: [before](mcp-token-measurement-before.json), [after full](mcp-token-measurement-after-full.json), [after compact](mcp-token-measurement-after-compact.json), [after daily](mcp-token-measurement-after-daily.json).
