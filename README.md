<div align="center">

<img src="assets/logo.svg" alt="AEC Model Bridge" height="120">

# AEC Model Bridge

MCP server and native add-in for AI-assisted Autodesk Revit workflows.

[![GitHub stars](https://img.shields.io/github/stars/Sam-AEC/aec-model-bridge?style=flat-square&logo=github&color=2563EB)](https://github.com/Sam-AEC/aec-model-bridge/stargazers)
[![Weekly downloads](https://img.shields.io/github/downloads/Sam-AEC/aec-model-bridge/latest/total?style=flat-square&logo=github&label=weekly%20downloads&color=2563EB)](https://github.com/Sam-AEC/aec-model-bridge/releases)
[![Latest release](https://img.shields.io/github/v/release/Sam-AEC/aec-model-bridge?style=flat-square&logo=github&color=2563EB)](https://github.com/Sam-AEC/aec-model-bridge/releases/latest)
[![Build status](https://img.shields.io/github/actions/workflow/status/Sam-AEC/aec-model-bridge/ci.yml?branch=main&style=flat-square&logo=githubactions&label=build)](https://github.com/Sam-AEC/aec-model-bridge/actions/workflows/ci.yml)
[![MCP Registry](https://img.shields.io/badge/MCP_Registry-active-0F766E?style=flat-square)](https://registry.modelcontextprotocol.io/?q=io.github.Sam-AEC%2Faec-model-bridge)
[![License](https://img.shields.io/badge/license-GPLv3%2B%20%2F%20Commercial-2563EB?style=flat-square)](LICENSING.md)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Revit](https://img.shields.io/badge/Revit-2024--2027-0696D7?style=flat-square)](https://www.autodesk.com/products/revit/)


[Install](#installation) | [Tools](docs/tools.md) | [Documentation](#documentation) | [Latest release](https://github.com/Sam-AEC/aec-model-bridge/releases/latest)

</div>

AEC Model Bridge connects MCP clients such as Claude Desktop, VS Code, GitHub
Copilot, and custom agents to a live Revit session.

The Python server handles MCP communication. The C# add-in executes commands
inside Revit through `ExternalEvent`, keeping API work on Revit's main thread.

## Highlights

- 100 MCP tools for model authoring, documentation, parameters, views, sheets,
  exports, worksharing, architecture, structure, MEP, geometry, and QA.
- Native Revit add-in with no pyRevit or Dynamo dependency.
- Revit 2024, 2025, 2026, and 2027 support.
- Reflection and in-process Python for advanced API workflows.
- Localhost-only bridge by default.
- Mock mode for development and automated testing without Revit.

## How It Works

```text
MCP client
    |
    | MCP over stdio
    v
Python MCP server
    |
    | HTTP on 127.0.0.1:3000
    v
AEC Model Bridge add-in
    |
    | ExternalEvent
    v
Revit API
```

## Installation

### Requirements

| Revit version | Add-in target | Required build tools |
|---|---|---|
| 2024 | .NET Framework 4.8 | .NET 8 SDK and .NET Framework 4.8 developer pack |
| 2025 | .NET 8 for Windows | .NET 8 SDK |
| 2026 | .NET 8 for Windows | .NET 8 SDK |
| 2027 | .NET 10 for Windows | .NET 10 SDK |

You also need Windows 10 or 11, Python 3.11 or later, and a licensed Revit
installation for the version you want to use.

### 1. Install the MCP server

```powershell
git clone https://github.com/Sam-AEC/aec-model-bridge.git
cd aec-model-bridge

py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e packages/mcp-server-revit
```

### 2. Install the Revit add-in

Set the version to match your Revit installation:

```powershell
$RevitVersion = Read-Host "Revit year (2024, 2025, 2026, or 2027)"

.\scripts\package.ps1 -RevitVersion $RevitVersion
.\scripts\install.ps1 -RevitVersion $RevitVersion
```

The installer places version-specific binaries in:

```text
C:\ProgramData\AECModelBridge\bin\<year>
```

The add-in manifest is installed per user in:

```text
%APPDATA%\Autodesk\Revit\Addins\<year>
```

Use `-AllUsers` with `install.ps1` to install the manifest under
`C:\ProgramData\Autodesk\Revit\Addins\<year>` instead.

To prepare binaries for every supported version in one pass:

```powershell
.\scripts\package.ps1 -RevitVersion All
```

Prebuilt packages are attached to GitHub releases when available. The source
installation above is the canonical path for all supported Revit versions.

### 3. Configure your MCP client

Use the Python executable from the virtual environment and choose a workspace
that the server may access:

```json
{
  "mcpServers": {
    "aec-model-bridge": {
      "command": "C:\\path\\to\\aec-model-bridge\\.venv\\Scripts\\python.exe",
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

VS Code users can start from [`.vscode/mcp.json`](.vscode/mcp.json).

Clients that support MCP Bundles can install the `.mcpb` file from the
[latest release](https://github.com/Sam-AEC/aec-model-bridge/releases/latest).
The Revit add-in is still required because the MCP server communicates with the
running desktop application.

### 4. Verify the connection

Restart Revit after installing the add-in, open a model, and run:

```powershell
Invoke-RestMethod http://127.0.0.1:3000/health
```

The response should report `healthy` and the active Revit version.

## Revit API Access

The typed MCP tools cover the common workflow surface and are the recommended
default for agents.

For work outside the tool catalog, `invoke_method`, `reflect_get`, and
`reflect_set` can work with public .NET API members. `execute_python` runs
IronPython inside Revit with `doc`, `uidoc`, `uiapp`, and `app` available.

These advanced tools run with the same permissions as the Revit process. Keep
the bridge on localhost and only use trusted MCP clients and prompts.

## Development

```powershell
# Python tests
python -m pytest packages/mcp-server-revit/tests

# Build one Revit version
$RevitVersion = Read-Host "Revit year (2024, 2025, 2026, or 2027)"
.\scripts\build-addin.ps1 -RevitVersion $RevitVersion -Configuration Release

# Build all supported versions
.\scripts\package.ps1 -RevitVersion All
```

CI builds the Python server and add-in targets for Revit 2024 through 2027.

## Documentation

- [Installation guide](docs/install.md)
- [Tool reference](docs/tools.md)
- [Architecture](docs/architecture.md)
- [Multi-platform integration handover](docs/integration-expansion-handover.md)
- [Configuration reference](docs/configuration-reference.md)
- [Security](docs/security.md)
- [MCP clients and registry](docs/marketplaces.md)
- [Contributing](CONTRIBUTING.md)

## Project

Maintained by [A. Sam Mohammad](https://github.com/Sam-AEC).
[LinkedIn](https://www.linkedin.com/in/a-sam-mohammad-92790416b) |
[Issues](https://github.com/Sam-AEC/aec-model-bridge/issues)

Version 1.1.0 and later is available under your choice of
[GPL-3.0-or-later with the Revit Linking Exception, or a separate commercial
license](LICENSING.md). The GPL option permits community use while allowing the
add-in to operate through Autodesk Revit APIs. Commercial terms are available
for proprietary distribution and negotiated requirements. Version 1.0.2 and
earlier remains available under the MIT License.

AEC Model Bridge is an independent project and is not sponsored, endorsed, or
provided by Autodesk. Autodesk and Revit are trademarks of the Autodesk group
of companies. See [TRADEMARKS.md](TRADEMARKS.md).
