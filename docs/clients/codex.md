# OpenAI Codex (CLI and IDE extension)

Status: **UNVERIFIED.** The file location and snippet below come from memory of Codex's documentation. They have not been tested against a live install. If something does not match, check the client's own docs and open an issue.

Before you start, finish the [install guide](../install.md) (the Revit add-in is a separate install), and install [uv](https://docs.astral.sh/uv/) so that `uvx` is on your PATH. The server entry is the same one the README install buttons use. It starts the server in live mode. Change `MCP_REVIT_MODE` to `mock` to try it with sample data and no Revit.

## Where the config goes (UNVERIFIED)

`~/.codex/config.toml` (on Windows, `%USERPROFILE%\.codex\config.toml`). The CLI can also write it for you with `codex mcp add`.

## Snippet (UNVERIFIED)

```toml
[mcp_servers.aec-model-bridge]
command = "uvx"
args = [
  "--from",
  "git+https://github.com/Sam-AEC/aec-model-bridge#subdirectory=packages/mcp-server-revit",
  "aec-model-bridge",
]

[mcp_servers.aec-model-bridge.env]
MCP_REVIT_MODE = "bridge"
```

Command-line form (UNVERIFIED flags):

```powershell
codex mcp add aec-model-bridge --env MCP_REVIT_MODE=bridge -- uvx --from "git+https://github.com/Sam-AEC/aec-model-bridge#subdirectory=packages/mcp-server-revit" aec-model-bridge
```

Codex may ask before running tools. That is separate from the Revit approval gate. Approve plans in the Revit panel.

## Check it works

Ask the assistant to list the AEC Model Bridge tools. With Revit open and the **AEC Bridge** tab visible, ask it to read the model name. Model changes stay blocked until you approve a plan in the Revit panel. See [privacy](../privacy.md) for where data goes and [security](../security.md) for the trust model.
