<div align="center">

<img src="assets/logo.svg" alt="AEC Model Bridge" height="120">

# AEC Model Bridge

Independent Model Context Protocol integration for Autodesk Revit® software.

[![Release downloads](assets/downloads-total.svg)](https://github.com/Sam-AEC/aec-model-bridge/releases)
[![Downloads during the last 7 days](assets/downloads-7d.svg)](metrics/downloads.json)
[![Downloads during the last 30 days](assets/downloads-30d.svg)](metrics/downloads.json)
[![Latest release](https://img.shields.io/github/v/release/Sam-AEC/aec-model-bridge?style=flat-square)](https://github.com/Sam-AEC/aec-model-bridge/releases/latest)
[![Build and test](https://github.com/Sam-AEC/aec-model-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/Sam-AEC/aec-model-bridge/actions/workflows/ci.yml)
[![Official MCP Registry](https://img.shields.io/badge/MCP_Registry-active-0F766E?style=flat-square)](https://registry.modelcontextprotocol.io/?q=io.github.Sam-AEC%2Faec-model-bridge)
[![License: MIT](https://img.shields.io/badge/license-MIT-0078D4?style=flat-square)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Revit 2024-2027](https://img.shields.io/badge/Revit-2024--2027-0696D7?style=flat-square)](https://www.autodesk.com/products/revit/)

[Quick start](#quick-start) | [Tools](docs/tools.md) | [Architecture](docs/architecture.md) | [Security](docs/security.md) | [GitHub profile](https://github.com/Sam-AEC) | [LinkedIn](https://www.linkedin.com/in/a-sam-mohammad-92790416b)

</div>

## What This Project Does

This repository connects MCP clients such as Claude Desktop, VS Code, and custom agents to Autodesk Revit.

It has two runtime components:

- A Python MCP server that exposes tools to the AI client.
- A C# Revit add-in that executes commands on Revit's main thread through `ExternalEvent`.

The bridge currently implements 103 active command routes across model authoring, documentation, parameters, views, sheets, exports, worksharing, MEP, structure, geometry, and model inspection.

## Download Activity

The repository snapshots GitHub release-asset downloads every day and generates
the badges and chart from [tracked metrics](metrics/downloads.json).

<div align="center">
  <a href="metrics/downloads.json">
    <img src="assets/downloads-history.svg" alt="AEC Model Bridge GitHub release download history" width="920">
  </a>
</div>

Daily tracking started on June 11, 2026. The 7-day and 30-day badges show
`tracking` until a complete baseline exists. GitHub does not provide historical
per-day release-download data, so earlier daily totals cannot be reconstructed
reliably. Counts exclude repository clones and GitHub-generated source archives.

## Why Use It

- Direct Revit API execution without requiring pyRevit or Dynamo.
- Localhost bridge with Revit-safe main-thread dispatch.
- Typed tools for common BIM operations.
- Reflection and in-process Python escape hatches for advanced workflows.
- Mock mode for development and testing without Revit.
- Version-specific builds for Revit 2024 through Revit 2027.

## Curated Tools and Broad API Access

AEC Model Bridge provides two complementary access layers:

| Access layer | Purpose | Trade-off |
|---|---|---|
| 100 typed MCP tools backed by 103 active bridge routes | Predictable model authoring, queries, documentation, exports, worksharing, and QA | Easier for agents to discover, validate, audit, and call reliably |
| `revit.invoke_method`, `revit.reflect_get`, and `revit.reflect_set` | Invoke public .NET methods and chain returned Revit objects without adding a dedicated route | Broad, but complex overloads and argument types are not always representable through JSON |
| `revit.execute_python` | Run IronPython inside the Revit process with `doc`, `uidoc`, `uiapp`, `app`, and the Revit API assemblies available | Broadest access, but less predictable and equivalent to privileged local code execution |

The Python and reflection tools make a large part of the public Revit desktop
API reachable even when no dedicated MCP route exists. They do not guarantee
literal access to every API surface. Non-public APIs, unsupported IronPython
interop, complex generic or overloaded signatures, and operations requiring a
different Revit execution context can still require a compiled command.

The curated routes are therefore not the limit of the product. They are the
reliable, typed layer for common work. The universal tools are an advanced
fallback for operations that have not yet been formalized as stable routes.

## Compatibility

| Revit | Add-in target | Status |
|---|---|---|
| 2024 | .NET Framework 4.8 | Supported |
| 2025 | .NET 8 for Windows | Supported |
| 2026 | .NET 8 for Windows | Supported |
| 2027 | .NET 10 for Windows | Supported |

Revit 2027 support is compiled against the installed Autodesk Revit 2027 API assemblies.

## Quick Start

### Prerequisites

- Windows 10 or 11
- Autodesk Revit 2024-2027
- Python 3.11 or later
- The .NET SDK required by the selected Revit version

### 1. Clone and install the MCP server

```powershell
git clone https://github.com/Sam-AEC/aec-model-bridge.git
cd aec-model-bridge
pip install -e packages/mcp-server-revit
```

### 2. Build, package, and install the Revit add-in

For Revit 2027:

```powershell
.\scripts\build-addin.ps1 -RevitVersion 2027
.\scripts\package.ps1 -RevitVersion 2027
.\scripts\install.ps1 -RevitVersion 2027
```

The installer places:

- Version-specific binaries in `C:\ProgramData\AECModelBridge\bin\{year}`
- The manifest in `%APPDATA%\Autodesk\Revit\Addins\2027`
- Default configuration in `C:\ProgramData\AECModelBridge\config`

Restart Revit after installing or replacing the add-in.

### 3. Configure an MCP client

Example Claude Desktop configuration:

```json
{
  "mcpServers": {
    "revit": {
      "command": "python",
      "args": ["-m", "revit_mcp_server.mcp_server"],
      "env": {
        "MCP_REVIT_BRIDGE_URL": "http://127.0.0.1:3000",
        "MCP_REVIT_MODE": "bridge"
      }
    }
  }
}
```

The repository also includes [`.vscode/mcp.json`](.vscode/mcp.json) for VS Code and GitHub Copilot.

### 4. Verify the bridge

Start Revit, then run:

```powershell
Invoke-RestMethod http://127.0.0.1:3000/health
```

For Revit 2027, the response should include:

```json
{
  "status": "healthy",
  "revit_version": "2027"
}
```

## Architecture

```text
MCP client
    |
    | stdio / MCP
    v
Python MCP server
    |
    | HTTP on 127.0.0.1:3000
    v
C# Revit bridge add-in
    |
    | ExternalEvent on Revit main thread
    v
Autodesk Revit API
```

The HTTP listener receives requests off the Revit UI thread. Commands are queued and executed through `ExternalEvent`, which is required for safe Revit API access.

## Tool Coverage

The active bridge command surface includes:

- Documents, levels, grids, walls, floors, roofs, rooms, and families
- Parameters, project parameters, shared parameters, and batch updates
- Views, view templates, sheets, title blocks, schedules, and annotations
- Selection, transforms, groups, links, worksets, and synchronization
- Structural columns, beams, foundations, ducts, pipes, and conduits
- PDF, DWG, IFC, Navisworks, schedule, image, and rendering exports
- Warnings, quantities, clashes, geometry, bounding boxes, and model queries
- Reflection-based API calls and in-process Python execution

See [docs/tools.md](docs/tools.md) for the tool reference.

## Security

The bridge listens on `127.0.0.1` by default. Do not expose port `3000` to a network without authentication and transport security.

The `execute_python`, `invoke_method`, `reflect_get`, and `reflect_set` tools are privileged capabilities. They can modify the active model and execute broad API operations. Restrict them in shared or production environments and keep backups of important models.

Do not expose these tools to untrusted MCP clients, users, prompts, or network
connections. `execute_python` is intentionally not a sandbox.

See [docs/security.md](docs/security.md) for the security model and [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Current Limitations

- Some source directories are excluded from compilation while their APIs are stabilized.
- Experimental command implementations are not advertised until they are active in the bridge.
- Automated tests cover the Python server; full Revit integration testing still requires a licensed Windows/Revit environment.

## Development

Run the Python test suite:

```powershell
python -m pytest packages/mcp-server-revit/tests
```

Build a specific Revit add-in:

```powershell
.\scripts\build-addin.ps1 -RevitVersion 2027 -Configuration Release
```

Package all supported versions:

```powershell
.\scripts\package.ps1 -RevitVersion All
```

## Documentation

- [Installation](docs/install.md)
- [Tool reference](docs/tools.md)
- [Architecture](docs/architecture.md)
- [Configuration reference](docs/configuration-reference.md)
- [Build and install scripts](docs/build-and-install-scripts.md)
- [Target frameworks and dependencies](docs/target-frameworks-and-dependencies.md)
- [MCP marketplaces](docs/marketplaces.md)
- [Contributing](CONTRIBUTING.md)

## License

This repository is currently distributed under the [MIT License](LICENSE).

## Maintainer

AEC Model Bridge is maintained by
[A. Sam Mohammad](https://github.com/Sam-AEC).
Professional background and contact:
[LinkedIn](https://www.linkedin.com/in/a-sam-mohammad-92790416b).

## Trademark and Affiliation Notice

AEC Model Bridge is an independent project. It is not sponsored, endorsed, or
provided by Autodesk.

Autodesk and Revit are trademarks of the Autodesk group of companies. Sam-AEC
is not affiliated with Autodesk.

The project uses the documented Revit desktop API and does not distribute
Autodesk API assemblies, product icons, or other Autodesk software. Users must
provide their own properly licensed installation. See [TRADEMARKS.md](TRADEMARKS.md).
