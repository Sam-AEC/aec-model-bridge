# Other MCP clients

Status: **UNVERIFIED.** File locations and snippets below come from memory of each client's documentation. None has been tested on a live install. If something does not match, check the client's own docs and open an issue.

Before you start, finish the [install guide](install.md) (the Revit add-in is a separate install) and install [uv](https://docs.astral.sh/uv/) so `uvx` is on your PATH. Each entry starts the server in live mode; set `MCP_REVIT_MODE` to `mock` to try it with sample data and no Revit. Menu names change between versions.

After saving, ask the assistant to list the AEC Model Bridge tools. With Revit open and the **AEC Bridge** tab visible, ask it to read the model name. Model changes stay blocked until you approve a plan in the Revit panel, whatever auto-approve the client has. See [privacy](privacy.md) and [security](security.md).

## Prompts and resources

Besides tools, the server offers MCP prompts and read-only resources. Support depends on the client: many show prompts as slash commands or a prompt picker, and some ignore resources.

Prompts (each is short text that names real tools; none approves anything for you):

| Prompt | Use |
| --- | --- |
| `qa_review` | Warnings, QA/QC checks and a report. Read-only. Optional `rule_pack`, `category`. |
| `parameter_fix` | Find elements, draft a plan, wait for your approval in the panel, read back. Needs `category`, `parameter`, `value`; optional `level`. |
| `sheet_prep` | Sheet and view checks before issue. Read-only. |
| `handover_report` | Build the QA hand-over report. |
| `first_run` | A short tour that changes nothing; fine in mock mode. |

Resources (JSON, redacted like tool results, ids validated, nothing writable):

| URI | Content |
| --- | --- |
| `aec://workspace/snapshots` | Saved snapshots, newest first (up to 100). |
| `aec://snapshot/{id}/summary` | Counts, source and coverage of one snapshot, not its elements. |
| `aec://plans/pending` | Pending plan ids, state and summary. |
| `aec://plan/{id}` | One plan. |
| `aec://proof/{id}` | The proof bundle of an executed plan. |
| `aec://qa/latest` | Issue counts by severity and status for the latest QA/QC run. |

## Cline (VS Code)

*MCP Servers, Installed, Configure MCP Servers* opens `cline_mcp_settings.json`. Cline can also install by itself from [llms-install.md](../llms-install.md). Leave its auto-approve off for tools that change the model.

```json
{"mcpServers":{"aec-model-bridge":{"command":"uvx","args":["--from","git+https://github.com/Sam-AEC/aec-model-bridge#subdirectory=packages/mcp-server-revit","aec-model-bridge"],"env":{"MCP_REVIT_MODE":"bridge"}}}}
```

## OpenAI Codex (CLI and IDE)

`~/.codex/config.toml` (Windows: `%USERPROFILE%\.codex\config.toml`), or run `codex mcp add`. Codex may ask before running tools; that is separate from the Revit approval gate.

```toml
[mcp_servers.aec-model-bridge]
command = "uvx"
args = ["--from", "git+https://github.com/Sam-AEC/aec-model-bridge#subdirectory=packages/mcp-server-revit", "aec-model-bridge"]
env = { MCP_REVIT_MODE = "bridge" }
```

## Gemini CLI

`~/.gemini/settings.json` (Windows: `%USERPROFILE%\.gemini\settings.json`), or `.gemini/settings.json` in one project. Add it next to existing settings. `/mcp` lists connected servers. There is no `gemini-extension.json` yet, so `gemini extensions install` does not work.

```json
{"mcpServers":{"aec-model-bridge":{"command":"uvx","args":["--from","git+https://github.com/Sam-AEC/aec-model-bridge#subdirectory=packages/mcp-server-revit","aec-model-bridge"],"env":{"MCP_REVIT_MODE":"bridge"}}}}
```

## JetBrains IDEs (AI Assistant)

*Settings, Tools, AI Assistant, Model Context Protocol (MCP), Add*, then choose "As JSON" and paste. The IDE keeps the file itself. Junie has its own MCP settings, not checked here.

```json
{"mcpServers":{"aec-model-bridge":{"command":"uvx","args":["--from","git+https://github.com/Sam-AEC/aec-model-bridge#subdirectory=packages/mcp-server-revit","aec-model-bridge"],"env":{"MCP_REVIT_MODE":"bridge"}}}}
```

## Visual Studio 2022 (17.14 or later) and 2026

`.mcp.json` next to the `.sln`, or `%USERPROFILE%\.mcp.json` for all solutions. It may also read `.vscode/mcp.json`; this repository ships [one](../.vscode/mcp.json). Note the top-level `servers` key. Use Copilot Chat in agent mode and confirm the server the first time.

```json
{"servers":{"aec-model-bridge":{"command":"uvx","args":["--from","git+https://github.com/Sam-AEC/aec-model-bridge#subdirectory=packages/mcp-server-revit","aec-model-bridge"],"env":{"MCP_REVIT_MODE":"bridge"}}}}
```

## Windsurf

`%USERPROFILE%\.codeium\windsurf\mcp_config.json` (Cascade panel, MCP servers, configure). Create it if missing, or add to the existing `mcpServers`. Refresh the MCP list after saving.

```json
{"mcpServers":{"aec-model-bridge":{"command":"uvx","args":["--from","git+https://github.com/Sam-AEC/aec-model-bridge#subdirectory=packages/mcp-server-revit","aec-model-bridge"],"env":{"MCP_REVIT_MODE":"bridge"}}}}
```
