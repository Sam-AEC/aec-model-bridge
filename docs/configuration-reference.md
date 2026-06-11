# Configuration Reference

This page documents the main environment variables, package metadata, and runtime settings used by the Revit MCP bridge.

## Runtime Modes

The server supports two runtime modes:

- `mock`: uses the built-in mock bridge for CI, development, and tests.
- `bridge`: connects to the Revit add-in over HTTP on `127.0.0.1:3000`.

## Environment Variables

| Variable | Required | Default | Description |
|---|---:|---|---|
| `MCP_REVIT_MODE` | Yes | `mock` | Selects the active bridge mode. |
| `MCP_REVIT_BRIDGE_URL` | Bridge mode | `http://127.0.0.1:3000` | URL of the Revit bridge listener. |
| `MCP_REVIT_ALLOWED_DIRECTORIES` | Yes | none | Semicolon-separated directories the server may access. |
| `MCP_REVIT_WORKSPACE_DIR` | Yes | none | Root directory for generated files and workspace-backed tools. |
| `MCP_REVIT_AUDIT_LOG` | No | `workspace/audit.jsonl` | Audit log path used by the security layer. |
| `REVIT_SDK` | Build only | unset | Optional path used by the add-in build scripts. |

## Package and Registry Metadata

The Python package and MCP registry metadata are defined in:

- `packages/mcp-server-revit/pyproject.toml`
- `packages/mcp-server-revit/manifest.json`
- `server.json`

The current package name is `aec-model-bridge`, and the official repository URL is:

- https://github.com/Sam-AEC/aec-model-bridge

## MCP Client Example

```json
{
  "mcpServers": {
    "revit": {
      "command": "python",
      "args": ["-m", "revit_mcp_server.mcp_server"],
      "env": {
        "MCP_REVIT_MODE": "bridge",
        "MCP_REVIT_BRIDGE_URL": "http://127.0.0.1:3000",
        "MCP_REVIT_WORKSPACE_DIR": "C:\\RevitProjects",
        "MCP_REVIT_ALLOWED_DIRECTORIES": "C:\\RevitProjects"
      }
    }
  }
}
```

## Notes

- The server should be run from the repository root or an environment where the package is installed in editable mode.
- For Revit integration, make sure the Revit add-in is installed and Revit is running before testing the bridge endpoint.
