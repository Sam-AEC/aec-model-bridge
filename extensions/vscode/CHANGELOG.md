# Changelog

The extension version follows the repository `VERSION` file. Release notes for the server itself are in the [main changelog](https://github.com/Sam-AEC/aec-model-bridge/blob/main/CHANGELOG.md).

## Unreleased

- Initial VS Code extension, available for local build and review.
- Registers the AEC Model Bridge MCP server (stdio) with VS Code, using the bundled Python when present and `uvx` otherwise.
- Settings for bridge or mock mode, Revit year, workspace folder and approval mode.
- Commands: Check connection, Open install guide, Use mock mode.
- Status bar item showing Connected or Not connected, with the Revit year.
- Runs on the local VS Code host, respects workspace settings and warns based on the actual server approval mode before startup.
- Update test and packaging tools to Vitest 4 and VSCE 4 to remove reported dependency vulnerabilities; build with Node 22 or newer.
