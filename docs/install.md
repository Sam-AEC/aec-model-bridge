# Installation

AEC Model Bridge has two components:

1. A Python MCP server used by the AI client.
2. A native add-in loaded by Revit.

Both are required for live Revit automation. Mock mode only requires the Python
server.

## Requirements

| Revit version | Add-in target | Build requirement |
|---|---|---|
| 2024 | .NET Framework 4.8 | .NET 8 SDK and .NET Framework 4.8 developer pack |
| 2025 | .NET 8 for Windows | .NET 8 SDK |
| 2026 | .NET 8 for Windows | .NET 8 SDK |
| 2027 | .NET 10 for Windows | .NET 10 SDK |

General requirements:

- Windows 10 or 11
- Python 3.11 or later
- Git
- A licensed Revit installation for live bridge mode

## Install From Source

Clone the repository and create a virtual environment:

```powershell
git clone https://github.com/Sam-AEC/aec-model-bridge.git
cd aec-model-bridge

py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e packages/mcp-server-revit
```

Choose the Revit version installed on your machine:

```powershell
$RevitVersion = Read-Host "Revit year (2024, 2025, 2026, or 2027)"
```

Build, package, and install the matching add-in:

```powershell
.\scripts\package.ps1 -RevitVersion $RevitVersion
.\scripts\install.ps1 -RevitVersion $RevitVersion
```

The default installation is per user:

```text
Add-in manifest:
%APPDATA%\Autodesk\Revit\Addins\<year>\AECModelBridge.addin

Version-specific binaries:
C:\ProgramData\AECModelBridge\bin\<year>\

Configuration:
C:\ProgramData\AECModelBridge\config\default.json
```

For an all-user manifest installation:

```powershell
.\scripts\install.ps1 -RevitVersion $RevitVersion -AllUsers
```

To package every supported Revit version:

```powershell
.\scripts\package.ps1 -RevitVersion All
```

You can then run `install.ps1` once for each installed Revit year.

## Install From a Release

Download a package matching your Revit version from
[GitHub Releases](https://github.com/Sam-AEC/aec-model-bridge/releases).

Extract the archive, check the available folders under `bin`, and install the
matching year:

```powershell
Get-ChildItem .\bin -Directory
$RevitVersion = Read-Host "Choose one of the listed Revit years"
.\install.ps1 -RevitVersion $RevitVersion
```

If a prebuilt package is not available for your year, use the source
installation above.

## Configure an MCP Client

The server requires a bridge URL and an allowed workspace:

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

The allowed directories value accepts multiple paths separated by semicolons.

VS Code users can start from [`.vscode/mcp.json`](../.vscode/mcp.json).

Clients with MCP Bundle support can install the `.mcpb` asset from the latest
release. The Revit add-in must still be installed separately.

## Verify the Bridge

Restart Revit after installing or replacing the add-in. Open a model and run:

```powershell
Invoke-RestMethod http://127.0.0.1:3000/health
```

The response should include:

```json
{
  "status": "healthy",
  "revit_version": "<running Revit year>"
}
```

The reported year will match the running Revit version.

## Mock Mode

Mock mode runs the MCP server without Revit:

```powershell
$env:MCP_REVIT_MODE = "mock"
$env:MCP_REVIT_WORKSPACE_DIR = "C:\revit-workspace"
$env:MCP_REVIT_ALLOWED_DIRECTORIES = "C:\revit-workspace"

python -m revit_mcp_server
```

Run the automated tests with:

```powershell
python -m pytest packages/mcp-server-revit/tests
```

## Troubleshooting

### Bridge connection refused

- Confirm Revit is running.
- Confirm the `AEC Bridge` ribbon tab is present.
- Check that the manifest year matches the running Revit year.
- Check the bridge log at `%APPDATA%\AECModelBridge\Logs\bridge.jsonl`.
- Confirm no other process is using port `3000`.

### Add-in build fails

- Run `dotnet --list-sdks` and confirm the required SDK is installed.
- For Revit 2024, install the .NET Framework 4.8 developer pack.
- Confirm the selected `-RevitVersion` is one of `2024`, `2025`, `2026`, or
  `2027`.
- If Revit is not installed on the build machine, the project uses matching
  Revit API reference packages for compilation.

### Workspace access denied

- Use absolute paths for `MCP_REVIT_WORKSPACE_DIR`.
- Include every required directory in `MCP_REVIT_ALLOWED_DIRECTORIES`.
- Separate multiple Windows paths with semicolons.

See the [configuration reference](configuration-reference.md) and
[security guide](security.md) for advanced settings.
