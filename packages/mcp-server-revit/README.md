# AEC Model Bridge (Python Package)

Independent MCP integration for Autodesk Revit software, used by AI clients over stdio.

- Repository: https://github.com/Sam-AEC/aec-model-bridge
- Maintainer: [A. Sam Mohammad](https://github.com/Sam-AEC)
- LinkedIn: https://www.linkedin.com/in/a-sam-mohammad-92790416b
- MCP entrypoint: `python -m revit_mcp_server.mcp_server`
- Console scripts: `aec-model-bridge` and the compatibility alias `revit-mcp-server`
- Requires Python 3.11+
- The `.mcpb` bundle uses the MCPB `uv` runtime and prompts for a permitted workspace directory.

Environment variables (prefix `MCP_REVIT_`) include:

- `MCP_REVIT_WORKSPACE_DIR`
- `MCP_REVIT_ALLOWED_DIRECTORIES`
- `MCP_REVIT_MODE` (`mock` or `bridge`)
- `MCP_REVIT_BRIDGE_URL` (required for `bridge` mode)
- `MCP_REVIT_AUDIT_LOG`
- `MCP_REVIT_LOG_LEVEL`

Autodesk and Revit are trademarks of the Autodesk group of companies. Sam-AEC
is not affiliated with Autodesk.

## License

Version 1.1.0 and later is available under your choice of GPL-3.0-or-later with
the Revit Linking Exception, or a separate commercial license. Commercial
terms are available for proprietary distribution and negotiated requirements.
Version 1.0.2 and earlier remains MIT licensed. See `LICENSING.md`.

<!-- mcp-name: io.github.Sam-AEC/aec-model-bridge -->

