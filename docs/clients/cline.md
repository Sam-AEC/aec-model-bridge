# Cline (VS Code)

Status: **UNVERIFIED.** The file location and snippet below come from memory of Cline's documentation. They have not been tested against a live install. If something does not match, check the client's own docs and open an issue.

Before you start, finish the [install guide](../install.md) (the Revit add-in is a separate install), and install [uv](https://docs.astral.sh/uv/) so that `uvx` is on your PATH. The server entry is the same one the README install buttons use. It starts the server in live mode. Change `MCP_REVIT_MODE` to `mock` to try it with sample data and no Revit.

## Where the config goes (UNVERIFIED)

In Cline, open *MCP Servers*, then *Installed*, then *Configure MCP Servers*. That opens `cline_mcp_settings.json`, which lives in VS Code's global storage for the Cline extension (the extension id was `saoudrizwan.claude-dev` when this was written). Edit it there rather than looking for the path by hand.

## Snippet (UNVERIFIED)

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
    }
  }
}
```

Cline can also install the server by itself from [llms-install.md](../../llms-install.md) in the repository root. That file is written for Cline to follow and has not been tested with Cline.

Cline has its own auto-approve switches for tools. Leave auto-approve off for tools that change the model. The Revit approval gate still applies either way.

## Check it works

Ask the assistant to list the AEC Model Bridge tools. With Revit open and the **AEC Bridge** tab visible, ask it to read the model name. Model changes stay blocked until you approve a plan in the Revit panel. See [privacy](../privacy.md) for where data goes and [security](../security.md) for the trust model.
