# Deferred tool loading

The full tool list is about 83k tokens and `core` about 15k (see [MCP token budget](mcp-token-budget.md)). A client with tool search can leave most tool definitions out of the prompt and load each one when a search returns it. The prompt prefix then stays small and cacheable.

This page shows how to defer the AEC Model Bridge server and keep a short always-loaded set. Deferral changes what the model sees, not what the server allows. Every write still needs a plan that a person approves.

## The always-loaded set

These eight tools stay loaded. The list is `ALWAYS_LOADED_TOOLS` in `packages/mcp-server-revit/src/revit_mcp_server/tool_profiles.py`, and a test pins it.

| Tool | Why it stays loaded |
| --- | --- |
| `revit_get_context` | Mode, Dev flag and document at the start of every task |
| `snapshot_take` | One capture of the model for later questions |
| `snapshot_compute` | Answers over a snapshot in one call |
| `search_tools` | Finds any tool, including tools the profile hides |
| `context_report` | Profile, tool count and tool-list size |
| `plan_actions` | Drafts the plan for any write |
| `execute_plan` | Runs a plan after a person approves it |
| `list_pending_plans` | Plan state |

All eight are visible in the `core`, `daily` and `full` profiles. Together they are about 1,832 tokens.

In `tools/list` the server marks each of these tools with `"_meta": {"anthropic/alwaysLoad": true}`. No other tool carries the flag.

## Claude Code

Claude Code turns tool search on by default: MCP tools are deferred and Claude searches for them. A tool whose `_meta` has `"anthropic/alwaysLoad": true` loads up front. So the default plugin or `claude mcp add` setup already defers the server and keeps the eight tools loaded. No extra setting is needed.

The plugin's `.mcp.json` (unchanged, shown for reference):

```json
{
  "mcpServers": {
    "aec-model-bridge": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/Sam-AEC/aec-model-bridge#subdirectory=packages/mcp-server-revit",
        "aec-model-bridge"
      ],
      "env": {
        "MCP_REVIT_MODE": "bridge"
      }
    }
  }
}
```

Settings that change this, from the Claude Code MCP docs:

- Leave `alwaysLoad` out of the server entry. With `"alwaysLoad": true` every tool of the server loads up front. With `"alwaysLoad": false` every tool is deferred, including the eight marked ones (Claude Code v2.1.287 or later).
- `ENABLE_TOOL_SEARCH`: unset or `true` defers MCP tools. `auto` or `auto:N` defers only when tool definitions pass 10% (or N%) of the context window. `false` loads every tool up front.
- On models earlier than Claude Opus 4 and Sonnet 4, on some Google Cloud Agent Platform models and on Microsoft Foundry deployments hosted on Azure, Claude Code loads every tool up front.
- Run `/context` to see which tools are loaded and which are deferred.

Combine deferral with a profile when the client cannot defer: `MCP_REVIT_TOOL_PROFILE=core` in `env` lists about 58 tools.

UNVERIFIED: the `_meta` flag and the deferral behaviour were checked against the Claude Code docs, not observed in a live Claude Code session with this server.

## Claude API

This server speaks MCP over stdio on the machine that runs Revit. The API's MCP connector (`mcp_servers` and `mcp_toolset`) only reaches servers exposed over public HTTPS, so it cannot start this server. Do not expose the Revit bridge to the internet for this.

Use your own MCP client instead: start the server, read `tools/list`, and pass the tools to the Messages API with the tool search tool. Set `defer_loading: true` on every tool except the always-loaded set. At least one tool must stay non-deferred; the tool search tool itself must never be deferred.

```python
import anthropic

ALWAYS_LOADED = {
    "revit_get_context", "snapshot_take", "snapshot_compute", "search_tools",
    "context_report", "plan_actions", "execute_plan", "list_pending_plans",
}


def to_api_tools(mcp_tools):
    """mcp_tools: the Tool list from an MCP ClientSession.list_tools() call."""
    tools = [{"type": "tool_search_tool_bm25_20251119", "name": "tool_search_tool_bm25"}]
    for tool in mcp_tools:
        entry = {
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.inputSchema,
        }
        if tool.name not in ALWAYS_LOADED:
            entry["defer_loading"] = True
        tools.append(entry)
    return tools


client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-opus-5-5",
    max_tokens=16000,
    tools=to_api_tools(mcp_tools),
    messages=[{"role": "user", "content": "How many doors on Level 1 have no fire rating?"}],
)
```

Notes from the tool search docs:

- Send every tool definition on every request, deferred ones included. The API needs them to run the search and expand `tool_reference` blocks.
- Pass the assistant content back unchanged, including `server_tool_use` and `tool_search_tool_result` blocks. Never return a `tool_result` for a `srvtoolu_...` id.
- A deferred tool cannot also carry `cache_control`. Put the cache breakpoint on a non-deferred tool.
- `tool_search_tool_regex_20251119` is the regex variant; the BM25 variant takes natural-language queries.
- When Claude calls a tool, run it through your MCP session with `call_tool` and return the result as a `tool_result`. The server's approval gate applies to those calls as to any other client.

If you run the server behind your own remote HTTPS MCP endpoint (not shipped by this project), the connector shape is one `mcp_toolset` that defers the server and keeps the eight tools loaded, with the beta header `mcp-client-2025-11-20`:

```json
{
  "mcp_servers": [
    {"type": "url", "url": "https://mcp.example.com/mcp", "name": "aec-model-bridge"}
  ],
  "tools": [
    {"type": "tool_search_tool_bm25_20251119", "name": "tool_search_tool_bm25"},
    {
      "type": "mcp_toolset",
      "mcp_server_name": "aec-model-bridge",
      "default_config": {"defer_loading": true},
      "configs": {
        "revit_get_context": {"defer_loading": false},
        "snapshot_take": {"defer_loading": false},
        "snapshot_compute": {"defer_loading": false},
        "search_tools": {"defer_loading": false},
        "context_report": {"defer_loading": false},
        "plan_actions": {"defer_loading": false},
        "execute_plan": {"defer_loading": false},
        "list_pending_plans": {"defer_loading": false}
      }
    }
  ]
}
```

UNVERIFIED: neither snippet was run against the live API with this server. The field names come from the tool search and MCP connector docs.

## Two searches

The client's tool search finds deferred tools that the profile lists. The server's `search_tools` searches every registered tool and says which profile shows a hidden one. Both return exact tool names, and a client calls a tool by that name. A tool that the profile hides is never in `tools/list`, so client tool search cannot find it; `search_tools` can, and its `note` tells the person how to switch profile.

## Other clients

Codex, Cursor and other MCP clients: UNVERIFIED. Where a client has no deferral, use `MCP_REVIT_TOOL_PROFILE=core`.
