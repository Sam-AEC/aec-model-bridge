# AEC Model Bridge (Python Package)

Independent MCP integration for Autodesk Revit® software, used by AI clients over stdio.

- Repository: https://github.com/Sam-AEC/Autodesk-Revit-MCP-Server
- MCP entrypoint: `python -m revit_mcp_server.mcp_server`
- Console scripts: `aec-model-bridge` and the compatibility alias `revit-mcp-server`
- Requires Python 3.11+

Environment variables (prefix `MCP_REVIT_`) include:

- `WORKSPACE_DIR`
- `ALLOWED_DIRECTORIES`
- `MODE` (`mock` or `bridge`)
- `BRIDGE_URL` (required for `bridge` mode)
- `AUDIT_LOG`
- `LOG_LEVEL`

Autodesk and Revit are trademarks of the Autodesk group of companies. Sam-AEC
is not affiliated with Autodesk.

<!-- mcp-name: io.github.Sam-AEC/Autodesk-Revit-MCP-Server -->

