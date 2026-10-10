# Visual Studio 2022 (17.14 or later) and Visual Studio 2026

Status: **UNVERIFIED.** The file location and snippet below come from memory of Visual Studio's documentation. They have not been tested against a live install. If something does not match, check the client's own docs and open an issue.

Before you start, finish the [install guide](../install.md) (the Revit add-in is a separate install), and install [uv](https://docs.astral.sh/uv/) so that `uvx` is on your PATH. The server entry is the same one the README install buttons use. It starts the server in live mode. Change `MCP_REVIT_MODE` to `mock` to try it with sample data and no Revit.

## Where the config goes (UNVERIFIED)

- One solution: `.mcp.json` next to the `.sln` file.
- All solutions: `%USERPROFILE%\.mcp.json`.
- Visual Studio may also read `.vscode/mcp.json`. This repository ships one, see [`.vscode/mcp.json`](../../.vscode/mcp.json).

## Snippet (UNVERIFIED)

```json
{
  "servers": {
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

Visual Studio uses the VS Code layout, with a top-level `servers` key. Open Copilot Chat in agent mode and look for the tools in the tool picker. You may have to confirm the server the first time.

## Check it works

Ask the assistant to list the AEC Model Bridge tools. With Revit open and the **AEC Bridge** tab visible, ask it to read the model name. Model changes stay blocked until you approve a plan in the Revit panel. See [privacy](../privacy.md) for where data goes and [security](../security.md) for the trust model.
