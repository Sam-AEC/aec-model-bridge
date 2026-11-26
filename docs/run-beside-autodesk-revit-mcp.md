# Run beside Autodesk's Revit MCP server

Status: UNVERIFIED. The maintainers have not run AEC Model Bridge and Autodesk's Revit MCP server in one client. This page states what this repository's tool names are and how to keep the two servers apart in client configuration. Autodesk's tool names, defaults and behaviour are not documented here because they were not observed.

## What a clash is

An MCP client lists the tools of every configured server. If two servers offer a tool with the same name, the client may show one of them, rename one, or call the wrong one. How a client resolves this differs per client and is UNVERIFIED here. Check the client's own MCP documentation.

## Tool names in this server

Every tool name starts with a prefix from a fixed list, or is one of a small set of full names. The list is checked by `tests/test_tool_name_prefixes.py`, so a new tool with an unlisted name fails the test.

| Family | Prefix |
| --- | --- |
| Revit tools | `revit_` |
| Identity mapping | `aec_` |
| Other providers | `exporter_`, `graph_`, `ifc_`, `navisworks_`, `rhino_`, `snapshot_`, `speckle_`, `autodesk_data_` |
| Modules | the module id, for example `qaqc_checker_`, `parameter_manager_`, `model_inspector_` |
| Proxied tools (`MCP_PROXY_TARGETS`) | `proxy_<name>_` or `proxy_` |

Tools without a family prefix:

| Group | Names |
| --- | --- |
| Plans and approval | `plan_actions`, `plan_revert`, `execute_plan`, `list_pending_plans`, `get_proof_bundle`, `policy_show` |
| Human-only, not listed to AI clients | `approve_plan`, `reject_plan`, `rollback_plan` |
| Jobs | `job_status`, `job_cancel` |
| Discovery | `search_tools`, `context_report`, `module_list_commands` |

The full list is in [tools-generated.md](tools-generated.md).

## Configure both servers with distinct names

Give each server its own key in the client configuration. The key is the name the client shows and, in many clients, adds to the tool name. This repository uses `aec-model-bridge`. Use any other key for the second server.

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
      "env": { "MCP_REVIT_MODE": "bridge" }
    },
    "autodesk-revit-mcp": {
      "command": "<command from Autodesk's documentation>",
      "args": ["<arguments from Autodesk's documentation>"]
    }
  }
}
```

Replace the `autodesk-revit-mcp` entry with the values Autodesk documents. Other clients use the same two keys in their own format; see [clients.md](clients.md).

## Reduce overlap

- Set `MCP_REVIT_TOOL_PROFILE` to `core` or `daily` to list fewer tools. See [configuration-reference.md](configuration-reference.md) and [deferred-tool-loading.md](deferred-tool-loading.md). `search_tools` finds a hidden tool by name.
- Turn off tools per server in the client if it offers that setting.
- Write changes only through this server's plan flow: `plan_actions`, human approval, `execute_plan`. Leave the other server's write tools off or on its own approval setting. Two servers editing one open model at the same time is not tested.

## Open points

- A tool-name prefix option for the unprefixed names (`plan_actions`, `execute_plan`, `job_status` and the rest) does not exist. If a live test shows a clash, add it as a code change and follow [deprecation-policy.md](deprecation-policy.md) for any rename.
- Whether the client keeps both servers connected and routes calls correctly: UNVERIFIED.
