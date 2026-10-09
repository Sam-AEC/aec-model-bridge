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

See the [configuration reference](https://github.com/Sam-AEC/aec-model-bridge/blob/main/docs/configuration-reference.md)
and [release notes](https://github.com/Sam-AEC/aec-model-bridge/blob/main/CHANGELOG.md).

## License

[GPL-3.0-or-later with the Revit Linking Exception, or a commercial license](https://github.com/Sam-AEC/aec-model-bridge/blob/main/LICENSING.md).

Maintained by [A. Sam Mohammad](https://github.com/Sam-AEC).

<!-- mcp-name: io.github.Sam-AEC/aec-model-bridge -->

