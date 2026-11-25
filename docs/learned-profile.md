# Learned profile and usage counts

The `learned` tool profile lists the tools one person actually uses. It is built from local usage counts that the MCP server keeps in the workspace. Nothing is sent anywhere.

## Usage counts

- The server counts each call to a listed tool by tool name.
- It stores, per tool, the number of calls per UTC day and the last day the tool was used. It stores no arguments, no results, no model data and no user or machine names.
- Calls to unknown tools, hidden tools and human-only approval tools are not counted.
- File: `<workspace>/usage/tool-usage.json` (workspace: `MCP_REVIT_WORKSPACE_DIR`). The path is built with `safe_child` and cannot leave the workspace.
- Writes are atomic: a temp file next to it, then one replace. A failed write leaves the old file unchanged and never fails a tool call.
- Writes are rate limited: counts are kept in memory and merged into the file at most once a minute and when the server stops. Each write re-reads the file and adds to it, so two servers on one workspace keep both counts.
- Day counts older than 90 days are dropped on write.
- Turn counting off with `MCP_REVIT_USAGE_COUNTS=off` (also `0`, `false`, `no`). No file is written then. Any value other than on or off stops the server at startup.

Code: `packages/mcp-server-revit/src/revit_mcp_server/usage_counts.py`.

## Show or reset the counts

```bash
aec-model-bridge-usage show            # top 25 tools, last 30 days
aec-model-bridge-usage show --days 7 --limit 10 --json
aec-model-bridge-usage reset           # deletes the counts file
```

`python -m revit_mcp_server.usage_counts show` does the same without the console script.

## The `learned` profile

Set `MCP_REVIT_TOOL_PROFILE=learned` and restart the MCP server. The profile lists:

- every `core` tool,
- the always-loaded tools (`ALWAYS_LOADED_TOOLS`, see [deferred tool loading](deferred-tool-loading.md)),
- the `MCP_REVIT_LEARNED_TOP_N` most used tools of the last 30 days (default 25, 1 to 200),
- the approval tools, `search_tools` and `context_report`, which every profile lists.

With fewer than 50 counted calls in the last 30 days, or with counting off, the server uses `daily` instead. `context_report` then shows `profile: daily` and a `profile_detail` line with the reason.

The counts are read once at server start. The tool list stays the same for the whole session, as with every profile; new calls change the list only after a restart. `MCP_REVIT_TOOL_PROFILE_FILE` can narrow `learned` like any other profile, and cannot hide approval tools.

Tools outside the list are refused if called, and `search_tools` still finds them and names a profile that shows them.

## context_report and search_tools

- `context_report` has a `usage` section: whether counting is on, total calls and the 10 most used tools of the last 30 days, and `learned_listed_tools`, the number of tools `learned` would list.
- When `learned` would list at most 75% of the current list, the first tip suggests `MCP_REVIT_TOOL_PROFILE=learned`.
- `search_tools` orders matches with equal scores by usage in the last 30 days, then by name.
