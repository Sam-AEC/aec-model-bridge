# Configuration reference

This page lists the environment variables, package files and runtime modes of the Revit MCP server.

## Runtime modes

The server has three modes. Set the mode with `MCP_REVIT_MODE`.

- `mock`: uses built-in sample data. Use it for tests, development and trying the tools without Revit. This is the default.
- `bridge`: connects to a running Revit add-in. The server finds the add-in through its local registry entry, or through an explicit bridge URL.
- `replay`: serves Revit responses from a recorded cassette (`MCP_REVIT_CASSETTE`) and never contacts Revit. See [Record and replay](record-replay.md).

## Environment variables

| Variable | Required | Default | Description |
|---|---:|---|---|
| `MCP_REVIT_MODE` | No | `mock` | Selects `mock`, `bridge` or `replay`. Set `bridge` for live Revit. |
| `MCP_REVIT_RECORD` | No | unset | Bridge mode only. Records each bridge request and response to `<workspace>/cassettes/<name>.jsonl` with secrets, paths and user names masked. A plain name (letters, digits, `_`, `-`); `1`, `true`, `on` or `yes` pick a timestamped name. A path is refused and every Revit call then reports why. A cassette can still hold model data; review it before sharing. See [Record and replay](record-replay.md). |
| `MCP_REVIT_CASSETTE` | With `replay` | unset | Cassette file that `MCP_REVIT_MODE=replay` serves. A request with no recorded match fails with a plain error. |
| `MCP_REVIT_BRIDGE_URL` | No | auto-discovered | Explicit URL of the Revit bridge. Overrides registry discovery. |
| `MCP_REVIT_HOST_VERSION` | No | newest live Revit | Revit year to pick from the local registry, such as `2024` or `2026`. |
| `MCP_REVIT_BRIDGE_TRANSPORT` | No | `http` | `http` or `pipe`. With `pipe` the server sends requests over the named pipe that the selected Revit publishes as `pipe_name` in its registry entry. If the entry has no pipe, it logs a warning and uses HTTP. Off Windows, `pipe` is refused. Unset: the value of `AEC_BRIDGE_TRANSPORT`, then `http`. Any other value makes the bridge unavailable. UNVERIFIED in live Revit. See [ADR 0021](adr/0021-named-pipe-transport.md). |
| `MCP_REVIT_ALLOWED_DIRECTORIES` | No | the workspace directory | Directories the server may read and write, separated by semicolons. The path guard checks against exactly this list. A value you set always wins. |
| `MCP_REVIT_WORKSPACE_DIR` | No | `~/Documents/AEC Model Bridge` | Root folder for generated files and workspace-backed tools. The server creates the default folder the first time it needs it, so a one-click install works with no configuration. |
| `MCP_REVIT_AUDIT_LOG` | No | `audit.log` | Path of the audit log. A relative path resolves against the working directory of the server process. See [Logging and audit](logging-and-audit.md). |
| `MCP_REVIT_LOG_LEVEL` | No | `INFO` | Log level of the server. |
| `MCP_REVIT_REDACT_RESPONSES` | No | `off` | Masks personal data in tool responses and tool errors. `off` changes nothing extra. `basic` masks email addresses and the local OS user name. `strict` also masks person fields such as `author`, `owner`, `created_by` and `user`. Any other value fails closed to `strict`. Paths and secrets are always masked, at every level. Read on each call. It does not change what Revit or the audit log hold. |
| `MCP_REVIT_READ_MAX_CHARS` | No | `20000` | Size cap in characters for read-only tool results; `0` turns it off. Longer results are cut at list rows and carry a cursor. `response_options.max_chars` overrides it per call. A value that is not an integer is ignored. Read on each call. See [Read result cursors](read-cursors.md). |
| `MCP_REVIT_READ_CURSOR_TTL` | No | `600` | Seconds a read cursor stays valid, from 1 to 3600. Read when a cursor is stored or checked. |
| `MCP_REVIT_APPROVAL_MODE` | No | `ask_first` | One of `look_only`, `ask_first` (alias `required`) or `auto`; trimmed and case-insensitive. `look_only` refuses every tool that changes the model and lets reads through. `ask_first` needs a `plan_id` for an approved plan before a model change runs. `auto` turns the approval check off. Any other value fails closed to `ask_first` and logs a warning. The mode cannot be changed over MCP. Live-Revit behaviour is UNVERIFIED. See [Security](security.md). Leave it at `ask_first` unless you have a reason. |
| `MCP_REVIT_TOOL_PROFILE` | No | `full` | Which tools the MCP server lists: `full` (all, about 80k tokens), `daily` (hides Rhino, Speckle, Navisworks, IFC, MEP and a few more, about 62k), `core` (54 tools for the coordinator loop, about 14k), `learned` (`core`, the always-loaded tools and your most used tools from the local usage counts; falls back to `daily` with too little data, see [Learned profile](learned-profile.md)) or `custom` (needs the file below). Tools outside the profile are not listed and calls to them are refused. Read once at startup; restart the MCP server to change it. Approval tools are always visible. See [MCP token budget](mcp-token-budget.md). |
| `MCP_REVIT_TOOL_PROFILE_FILE` | No | unset | JSON file with `include` / `exclude` provider or module ID globs. Required for `custom`; narrows `full`, `daily`, `core` or `learned`. |
| `MCP_REVIT_LEARNED_TOP_N` | No | `25` | How many of the most used tools of the last 30 days `learned` adds to `core` and the always-loaded tools. Whole number from 1 to 200; any other value stops the server at startup. |
| `MCP_REVIT_USAGE_COUNTS` | No | `off` | `on` turns on local tool usage counts in `<workspace>/usage/tool-usage.json`: tool names, calls per day and last-used day only. `off` (or `0`, `false`, `no`) counts nothing and writes no file; `learned` then falls back to `daily`. Any other value stops the server at startup. Nothing is sent anywhere. See [Learned profile](learned-profile.md). |
| `MCP_REVIT_APPROVAL_TTL` | No | `28800` (8 hours) | Seconds an approved plan stays usable. After that the plan moves to `expired` and a person must approve a new plan; it is never renewed silently. `0` turns the limit off. A negative, fractional or non-numeric value falls back to the default (it never turns the limit off) and logs a warning. Checked when a call runs, not by a timer. See [ADR 0017](adr/0017-approval-document-binding-and-expiry.md). |
| `MCP_REVIT_PENDING_TTL` | No | `1209600` (14 days) | Seconds a drafted, not yet approved plan can still be approved. Older pending plans are left out of `list` and `list_pending_plans` (counted as `expired_hidden`; `list --all` or `include_expired` shows them), cannot be approved, and are never deleted. `0` turns the limit off. Same fallback rule as above. |
| `MCP_REVIT_POLICY_FILE` | No | unset | Path of a policy file (YAML or JSON) that adds refusals to `plan_actions` and `execute_plan`. Unset: `policy.yaml`, `policy.yml` or `policy.json` in the workspace folder, if present. A file that is named but missing or invalid refuses every write. See [Policy file](#policy-file). |
| `MCP_REVIT_MCP_APPS` | No | `true` | Offers the read-only plan review view `ui://aec-model-bridge/plan-review` (MCP Apps) and the `_meta.ui` keys on tools. The view cannot approve. `false` removes both. Read at startup. See [MCP Apps plan review view](mcp-apps.md). |
| `MCP_REVIT_VALIDATE_BRIDGE_PAYLOADS` | No | on | Checks each Revit add-in command payload against `contracts/bridge-commands.json` before sending. A payload that does not fit is refused and nothing is sent. `0`, `false`, `off` or `no` turns the check off; any other value keeps it on. Read on each call. See [Add-in command contract](bridge-command-contract.md). |
| `MCP_REVIT_ENABLE_USER_MODULES` | No | `false` | Set to `true` to load modules from `%LOCALAPPDATA%\AECModelBridge\modules`. See [Module authoring](module-authoring.md). |
| `MCP_REVIT_ALLOW_PYTHON_HOST` | No | `false` | Set to `true` to allow tools that run raw Python on the host, such as `revit_execute_python`. Leave it off unless you need it. |
| `MCP_REVIT_ANTHROPIC_API_KEY` | No | unset | Anthropic API key for the panel's built-in Claude chat (`agent_native.py`, ADR 0012). If you do not set it, the Claude chat falls back to the `claude` command-line tool when that is on your PATH. If neither is available, no AI provider is available. You can also put the key in a `.env` file. The hub reads it only at startup, so restart Revit after you set or change it. The panel's Settings view cannot set it. |
| `MCP_PANEL_HTTP_PORT` | No | `8787` | Port of the panel hub (loopback only). Read by the hub and by the add-in. |
| `MCP_PANEL_TOKEN_FILE` | No | `%LOCALAPPDATA%\AECModelBridge\panel-hub.token` | Path of the per-user panel hub token file. The first hub to start creates it (owner-only); the hub and every Revit add-in read it. Delete it and restart the hub to rotate the token. Never copy its contents into a config, chat or log. See [Security](security.md). |
| `AEC_BRIDGE_TRANSPORT` | No | unset | Read by the Revit add-in at start-up. Set to `pipe` to open a named pipe for the current Windows user beside the HTTP port, and publish its name in the registry entry. The Python server also reads it when `MCP_REVIT_BRIDGE_TRANSPORT` is unset. UNVERIFIED in live Revit. See [ADR 0021](adr/0021-named-pipe-transport.md). |
| `MCP_REVIT_LEGACY_PORT` | No | unset | Read by the Revit add-in, not the Python server. Set to `true` or `1` to bind the add-in to fixed port `3000` with no authentication. See [Security](security.md). |
| `AEC_BRIDGE_TURN_BUDGET_MS` | No | `40` | Read by the Revit add-in when Revit starts. Milliseconds one Revit turn may spend on queued read-only requests before it hands control back to Revit. Clamped to `0`-`200`; `0` runs one request per turn. Writes, unknown commands, exports, `revit.extract_snapshot` and `revit.check_clashes` always run alone in their own turn. A turn can exceed the budget by at most one command. Live behaviour is UNVERIFIED. |
| `AEC_BRIDGE_FAST_WAKE` | No | unset (off) | Read by the Revit add-in when Revit starts. `1` or `true` attaches an `Idling` handler that calls `SetRaiseWithoutDelay` while requests are still queued after a turn, so the next turn starts at once. CPU cost: Revit keeps one core busy while the handler is attached. It is attached only while the queue is non-empty and removed when it is empty, so idle CPU use stays at zero. The first request after an idle period still waits for Revit's normal pickup. Live behaviour is UNVERIFIED. |
| `AEC_BRIDGE_PYTHON_RECYCLE_RUNS` | No | `50` | Read by the Revit add-in when Revit starts. Scripts one warm IronPython engine runs before it is replaced (`revit_execute_python`). Clamped to `1`-`10000`; `1` turns the warm engine off: every script starts a new engine and it is shut down when the script ends. Only read-mode scripts share it: a write-mode script always starts a new engine, which is shut down when it ends. The reset that puts back stdout, stderr and sys.path runs at the end of each read-mode script, inside its read guard, so nothing the script left behind runs outside the guard. The engine is also replaced when the active document changes, when that reset fails, after a fatal runtime error, and after a script that touched the model in read mode or left a transaction open. Each script gets a new scope and its own output. Imported modules stay loaded between scripts. Live behaviour is UNVERIFIED. |
| `REVIT_SDK` | Build only | unset | Optional path used by the add-in build scripts. |

The Revit add-in honors the same explicit directory allowlist as the hub; it
does not add its default workspace to an explicit list. When the add-in launches
the hub without an allowlist, it scopes the hub to the effective workspace,
including a custom `MCP_REVIT_WORKSPACE_DIR`.

## Package and registry files

These files define the Python package and the MCP registry entry:

- `packages/mcp-server-revit/pyproject.toml`
- `packages/mcp-server-revit/manifest.json`
- `server.json`

The package name is `aec-model-bridge`. The official repository is https://github.com/Sam-AEC/aec-model-bridge.

## MCP client example

```json
{
  "mcpServers": {
    "revit": {
      "command": "python",
      "args": ["-m", "revit_mcp_server.mcp_server"],
      "env": {
        "MCP_REVIT_MODE": "bridge",
        "MCP_REVIT_HOST_VERSION": "2026",
        "MCP_REVIT_WORKSPACE_DIR": "C:\\RevitProjects",
        "MCP_REVIT_ALLOWED_DIRECTORIES": "C:\\RevitProjects"
      }
    }
  }
}
```

## Policy file

An optional policy adds refusals. It never approves or runs anything, and it can only make the server say no more often. Without a file nothing changes. The file is read every time it is needed, so a change applies to the next draft and to the next `execute_plan` of a plan that was drafted earlier. `policy_show` (read-only) returns the effective policy and its hash; the hash is also stored on each plan as `policy_hash`. An example is in [examples/policy.yaml](examples/policy.yaml).

| Key | Type | Refuses |
| --- | --- | --- |
| `blocked_tools` | list of tool names | any action that uses a listed tool |
| `allowed_tools` | list of tool names | any action whose tool is not listed (when the key is present) |
| `allowed_categories` | list of category names (`OST_` prefix and case ignored) | a plan that touches another category, or one whose category is unknown |
| `blocked_parameters` | list of parameter names (case ignored) | any action that sets a listed parameter |
| `max_elements_per_plan` | whole number | a plan naming more elements, or any action that names none |
| `max_actions_per_plan` | whole number | a plan with more actions |

Element, category, level and workset values come from the action arguments and, when the plan names one, the snapshot. Anything not known is reported as `unknown`; a rule that needs an unknown value refuses rather than guesses. An unknown key, a wrong type, a missing file named by `MCP_REVIT_POLICY_FILE` or a parse error is an invalid policy: every `plan_actions` and `execute_plan` call is refused with the reason until it is fixed. Direct writes in Dev or Auto mode do not go through a plan and are not covered.

## Plan preview and risk

`plan_actions`, `list_pending_plans` and `aec-model-bridge-approve show` add `preview` (rows of element id, UniqueId, parameter, before, after, tool), `preview_markdown` (the same table, at most 25 rows and an "N more" line) and `blast_radius` (`element_count`, `action_count`, `categories`, `levels`, `worksets`, `risk`). They are computed when a plan is shown, are not stored and are not part of the plan hash. Risk is `low` up to 10 elements and 5 actions, `medium` up to 100 elements and 25 actions, `high` above that. A plan is at least `medium` when an action names no element or a tool name says delete, purge or remove. These are estimates from the arguments, not a check of the live model.

## Command-line review (`aec-model-bridge-approve`)

`aec-model-bridge-approve show <plan_id>`, `--show <plan_id>` and `approve <plan_id>` print the same review before anything else happens:

- one table per action: element (id, plus name and Mark when the plan's snapshot can be read), parameter, old value -> new value. An action that sets no parameter shows its other arguments as the new value. An old value that was not recorded shows `(not captured)`.
- counts (actions, elements, parameters, changes, old values captured), tools and the risk estimate above.
- warnings: review warnings (hashed), unhashed legacy warnings, preview notes (actions that name no element, old values not captured, high risk), expiry and malformed actions.
- the short plan hash, the approval mode in force, the expiry time (`pending_ttl` or `approval_ttl`) and the document binding. The full hash is printed at the end; the approval is bound to it.

Old values and arguments come from the hashed plan. Element names and marks come from the snapshot and are not part of the hash.

Output is plain ASCII layout with no ANSI codes, so it works in Windows cmd and PowerShell. `--color` adds color only when stdout is a terminal that supports it (on Windows: Windows Terminal, ConEmu, ANSICON, VS Code or a set `TERM`) and `NO_COLOR` is unset or empty. Long values wrap to the terminal width (60 to 200 columns) without collapsing spaces. Text values print as JSON strings in double quotes, so `"A B"`, `"A  B"` and `" "` look different. Model text is escaped. Without `--all`, at most 30 change rows and 300 characters per value are printed, followed by a `+N more ..., use --all` line. Arguments of a parameter write that are not in the Element, Parameter or New column (for example the `filter` of `revit_batch_set_parameters_by_filter`) are printed on an `Other arguments:` line under the action's table, cut by the same rule. When anything is cut, `approve` says so above the confirmation prompt.

| Option | Commands | Effect |
| --- | --- | --- |
| `--show PLAN_ID` | none (top level) | Print the review and exit. Never approves. Same as `show PLAN_ID`. |
| `--all` | `--show`, `show`, `approve`, `reject`, `recover` | Print every row and full values. |
| `--json` | `--show`, `show` | Print the review as JSON and exit. Not accepted by `approve`. |
| `--color` | `--show`, `show`, `approve`, `reject`, `recover` | Color the review when supported (see above). |

The JSON review has `schema: "aec-model-bridge/plan-review"`, `schema_version: 1`, `plan_id`, `state`, `created_at`, `plan_hash`, `plan_hash_short`, `approval_mode` (`mode`, `configured_mode`, `auto_expires_at`), `expiry` (`applies`, `expired`, `reason`, `rule`, `ttl_seconds`, `expires_at`), `binding` (`recorded`, `bound`, and when bound `doc_title`, `revit_version`, `active_view_id`), `counts`, `tools`, `risk`, `warnings` (`source`, `text`), `approvable`, `not_approvable_reasons`, `actions` (each with `changes`: `element_id` as a string or null, `element_name`, `mark`, `unique_id`, `parameter`, `old`, `old_captured`, `new`, `new_is_arguments`; and `other_arguments`, the arguments no change column shows), `review`, `not_hashed_keys`, `snapshot_id` and `reverts_plan_id`. Values are not cut. `approvable` only reflects the plan's state, expiry and shape; it does not approve anything.

Approval is unchanged: the person types the plan id after the review. Without a terminal the command refuses unless `--yes` is given. The review never changes the plan file.

## Notes

- Run the server from the repository root, or from an environment where you installed the package in editable mode.
- For live Revit, install the add-in and start the Revit version you want before you test.
- To use several open Revit versions side by side, add one MCP client entry for each version. Give each entry its own `MCP_REVIT_HOST_VERSION`.
