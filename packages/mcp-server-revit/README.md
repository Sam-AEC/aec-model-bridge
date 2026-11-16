# AEC Model Bridge

Python MCP server for reviewing BIM model quality and fixing Revit parameters
with Claude, Codex and other MCP clients. Read-only tools inspect the model;
model changes require an approved plan by default.

[Get started](https://github.com/Sam-AEC/aec-model-bridge#quick-start) |
[Example workflows](https://github.com/Sam-AEC/aec-model-bridge#example-workflows) |
[Tool reference](https://github.com/Sam-AEC/aec-model-bridge/blob/main/docs/tools-generated.md)

Live Revit automation requires Windows, Revit 2024–2027 and the native Revit
add-in. The server also includes IFC inspection, Rhino and Grasshopper, and
Speckle providers. Navisworks integration is in progress. See the
[installation guide](https://github.com/Sam-AEC/aec-model-bridge/blob/main/docs/install.md).

## Run the server

Requires Python 3.11 or newer. To explore the tools in mock mode from a
repository checkout:

```powershell
python -m pip install -e packages/mcp-server-revit
$env:MCP_REVIT_MODE = "mock"
$env:MCP_REVIT_WORKSPACE_DIR = (Get-Location).Path
$env:MCP_REVIT_ALLOWED_DIRECTORIES = $env:MCP_REVIT_WORKSPACE_DIR
python -m revit_mcp_server.mcp_server
```

MCP clients start the server over stdio. The console command is
`aec-model-bridge`; `revit-mcp-server` remains available as a compatibility
alias. For development without Revit, set `MCP_REVIT_MODE=mock` to return canned
responses. The release `.mcpb` bundle uses the MCPB `uv` runtime and prompts for
a permitted workspace directory.

## Configuration

| Environment variable | Purpose |
| --- | --- |
| `MCP_REVIT_MODE` | `bridge` for a live application or `mock` for development |
| `MCP_REVIT_WORKSPACE_DIR` | Workspace root for server file operations |
| `MCP_REVIT_ALLOWED_DIRECTORIES` | Semicolon-separated permitted directories |
| `MCP_REVIT_HOST_VERSION` | Optional Revit year selector, such as `2026` |
| `MCP_REVIT_BRIDGE_URL` | Optional explicit bridge endpoint |
| `MCP_REVIT_AUDIT_LOG` | Audit log location |
| `MCP_REVIT_LOG_LEVEL` | Logging verbosity |
| `MCP_REVIT_TOOL_PROFILE` | Startup tool catalogue: `full` (default), `daily`, or `custom` |
| `MCP_REVIT_TOOL_PROFILE_FILE` | Optional JSON file of provider/module ID include/exclude globs; required for `custom` |

### Static tool profiles

| Profile | Available tools |
| --- | --- |
| `full` | All tools, as before. Human-only approval/rejection/rollback tools remain unavailable to AI clients. |
| `daily` | Keeps Revit sparing, groups, recipes, sections/tags/views, parameters, plans/jobs and general inspection. Hides `revit_mep` (including native duct/pipe creation), `revit_ifc`, and provider/module IDs matching `rhino*`, `speckle*`, `navisworks*`, `bcf_exchange*`, `clash_triage*`, `ifc*`. |
| `custom` | Tools whose provider or manifest module ID matches the file's include globs, minus exclusions. |

The owner can add `"MCP_REVIT_TOOL_PROFILE": "daily"` to this server's `env`
in `.mcp.json`, then restart the MCP connection. The default stays `full`.
Profiles and file contents are read once at startup; there is no live toggle.
Hidden tools are omitted from discovery and refused when called, including
plan/job targets. Panel registries retain their complete catalogue. Write
approval, human review and single-use approved actions are unchanged.

Example custom file (globs match provider IDs or manifest module IDs, not tool names):

```json
{"include": ["revit", "revit_*", "approval", "jobs", "parameter_manager", "selection_tools", "recipe_runner"], "exclude": ["revit_mep", "revit_ifc"]}
```

Set `MCP_REVIT_TOOL_PROFILE=custom` and `MCP_REVIT_TOOL_PROFILE_FILE` to its path.
Omitted `include` means `["*"]`; an empty include array selects nothing.
Exclusions always win. A file may also narrow `full` or `daily`; it cannot
restore daily's built-in exclusions. Invalid settings stop startup.
New commands inherit their manifest module's membership. A repository audit
found no calls to hidden modules in sibling `dynamoscript14`; its context,
Python, result, plan and execution calls remain available.

### Smaller read responses

Default responses retain their existing format and fields. For
`module_list_commands`, `revit_list_elements`, `revit_list_families`,
`revit_get_element_parameters` and `revit_list_views`, use optional
`response_options` to minify JSON and/or select dotted result paths. Arrays
are traversed automatically. For example:

```json
{"response_options": {"compact": true, "fields": ["modules.id", "modules.commands.id"]}}
```

That example lists module/command IDs without echoing every command schema.
Field selection affects only the returned payload, after redaction; provider
execution and stored data are unchanged. Errors and running-result diagnostics
are never field-filtered. Options require a synchronous call.
`plan_actions` supports compact JSON and optional omission of its echoed arguments:

```json
{"actions": [{"tool": "revit_execute_python", "arguments": {"script": "...", "mode": "write"}}], "response_options": {"compact": true, "omit_action_arguments": true}}
```

This returns a marked summary without `actions[].arguments` or identical
`actions[].diff.after` copies. It retains plan/action IDs, state, review,
before evidence and the hash of the full stored plan. A person reviews that
complete plan in the Revit panel or approval CLI before approving it.
Stored arguments and approval checks are unchanged; execution remains blocked
until human approval. Omission defaults to false and never applies to errors
or running-result diagnostics. Arbitrary field projection is unavailable for plans.
The shared server instructions explain approval once; every write tool still
has its `plan_id` schema and behavior annotations.

See [measured token costs](../../docs/mcp-token-budget.md) for the reproducible
mock baseline, per-module costs, heaviest schemas and before/after comparison.

See the [configuration reference](https://github.com/Sam-AEC/aec-model-bridge/blob/main/docs/configuration-reference.md)
and [release notes](https://github.com/Sam-AEC/aec-model-bridge/blob/main/CHANGELOG.md).

## License

[GPL-3.0-or-later with the Revit Linking Exception, or a commercial license](https://github.com/Sam-AEC/aec-model-bridge/blob/main/LICENSING.md).

Maintained by [A. Sam Mohammad](https://github.com/Sam-AEC).

<!-- mcp-name: io.github.Sam-AEC/aec-model-bridge -->

