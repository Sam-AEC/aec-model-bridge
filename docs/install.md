# Install AEC Model Bridge

AEC Model Bridge has two parts:

1. A Python MCP server that your AI client starts.
2. A native add-in that Revit loads.

You need both to work with a live Revit model. Mock mode needs only the Python
server. It uses sample data. Supported Revit versions are 2024 to 2027. For
release numbering, see [versioning](versioning.md).

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

## Download the installer

This is the easiest way to install on Windows. You do not need Python, Git or build tools.

1. Open the [latest release](https://github.com/Sam-AEC/aec-model-bridge/releases/latest)
   and download `AECModelBridge-Setup-<version>.exe`.
2. Close Revit, then double-click the file. Windows SmartScreen may warn that the
   publisher is unknown, because the installer is not code-signed yet. Choose
   **More info**, then **Run anyway**. To check the download, compare it with the
   checksum in `SHA256SUMS.txt` on the same page.
3. On the *Revit versions* page, the installer has already ticked the Revit years it
   found on your computer. Change them if you like. You can also tick *Set up Claude
   Desktop and VS Code*. The installer first copies your current settings to a
   `.aec-backup-<date>` file.
4. Start Revit and look for the **AEC Bridge** tab.

The installer needs no administrator rights. It puts the add-in in
`C:\ProgramData\AECModelBridge\bin\<year>`, the bundled Python and MCP server in
`C:\ProgramData\AECModelBridge\python`, and a per-user manifest in
`%APPDATA%\Autodesk\Revit\Addins\<year>`. Running the installer again upgrades the
existing install.
To remove everything, open *Apps > Installed apps > AEC Model Bridge > Uninstall*.
Close Revit first. Both Setup and the uninstaller stop if Revit is running.

For a silent install (IT deployment):

```powershell
.\AECModelBridge-Setup-<version>.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /COMPONENTS="y2025,y2026"
```

`/COMPONENTS` takes `y2024`, `y2025`, `y2026` and `y2027`. Leave it out to use the
Revit versions the installer detects. Add `/TASKS="mcpclients"` to set up Claude Desktop
and VS Code. Add `/LOG="setup.log"` to keep a log. To build the installer yourself, see
[build and install scripts](build-and-install-scripts.md).

## Install From Source

Clone the repository and create a virtual environment:

```powershell
git clone https://github.com/Sam-AEC/aec-model-bridge.git
cd aec-model-bridge

py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e packages/mcp-server-revit
```

Enter the Revit year installed on your machine:

```powershell
$RevitVersion = Read-Host "Revit year (2024, 2025, 2026, or 2027)"
```

Build, package and install the add-in for that year. To only build, run
`.\scripts\build-addin.ps1 -RevitVersion 2026` (use your Revit year):

```powershell
.\scripts\package.ps1 -RevitVersion $RevitVersion
.\scripts\install.ps1 -RevitVersion $RevitVersion
```

The default install is per user. It uses these locations:

```text
Add-in manifest:
%APPDATA%\Autodesk\Revit\Addins\<year>\AECModelBridge.addin

Version-specific binaries:
C:\ProgramData\AECModelBridge\bin\<year>\

Configuration:
C:\ProgramData\AECModelBridge\config\default.json
```

To install the manifest for all users:

```powershell
.\scripts\install.ps1 -RevitVersion $RevitVersion -AllUsers
```

To package every supported Revit version:

```powershell
.\scripts\package.ps1 -RevitVersion All
```

Then run `install.ps1` once for each Revit year you have installed.

## Install From a Release

Download a package matching your Revit version from
[GitHub Releases](https://github.com/Sam-AEC/aec-model-bridge/releases).

Extract the archive and list the folders under `bin`. Then install your year:

```powershell
Get-ChildItem .\bin -Directory
$RevitVersion = Read-Host "Choose one of the listed Revit years"
.\install.ps1 -RevitVersion $RevitVersion
```

If there is no prebuilt package for your year, use the source install above.

## Configure an MCP client

If you do not set a workspace, the server uses `~/Documents/AEC Model Bridge`.
The examples below set one explicitly. In bridge mode the server connects to the
newest open Revit by default. Set `MCP_REVIT_HOST_VERSION` to pick a specific
Revit year:

```json
{
  "mcpServers": {
    "aec-model-bridge": {
      "command": "C:\\path\\to\\aec-model-bridge\\.venv\\Scripts\\python.exe",
      "args": ["-m", "revit_mcp_server.mcp_server"],
      "env": {
        "MCP_REVIT_MODE": "bridge",
        "MCP_REVIT_WORKSPACE_DIR": "C:\\RevitProjects",
        "MCP_REVIT_ALLOWED_DIRECTORIES": "C:\\RevitProjects"
      }
    },
    "aec-model-bridge-revit-2026": {
      "command": "C:\\path\\to\\aec-model-bridge\\.venv\\Scripts\\python.exe",
      "args": ["-m", "revit_mcp_server.mcp_server"],
      "env": {
        "MCP_REVIT_MODE": "bridge",
        "MCP_REVIT_HOST_VERSION": "2026",
        "MCP_REVIT_WORKSPACE_DIR": "C:\\RevitProjects",
        "MCP_REVIT_ALLOWED_DIRECTORIES": "C:\\RevitProjects"
      }
    }
  }
}
```

`MCP_REVIT_ALLOWED_DIRECTORIES` accepts several paths separated by semicolons.

In VS Code, you can start from [`.vscode/mcp.json`](../.vscode/mcp.json).

If your client supports MCP Bundles, install the `.mcpb` file from the latest
release. You still need to install the Revit add-in separately.

## Verify the bridge

When Revit starts, the add-in writes an endpoint file under
`%LOCALAPPDATA%\AECModelBridge\registry`. This command reads that file and calls the bridge:

```powershell
$registry = Get-ChildItem "$env:LOCALAPPDATA\AECModelBridge\registry\revit-*.json" | Select-Object -First 1
$switch = Get-Content $registry.FullName -Raw | ConvertFrom-Json
Invoke-RestMethod "$($switch.endpoint)/health"
```

The response should include:

```json
{
  "status": "healthy",
  "revit_version": "<running Revit year>"
}
```

The reported year matches the Revit version that is running.

## Mock mode

Mock mode runs the MCP server without Revit. It returns sample data:

```powershell
$env:MCP_REVIT_MODE = "mock"
$env:MCP_REVIT_WORKSPACE_DIR = "C:\revit-workspace"
$env:MCP_REVIT_ALLOWED_DIRECTORIES = "C:\revit-workspace"

python -m revit_mcp_server
```

To run the automated tests:

```powershell
python -m pytest packages/mcp-server-revit/tests
```

## Troubleshooting

### Bridge connection refused

- Confirm Revit is running.
- Confirm the `AEC Bridge` ribbon tab is present. It has Connection, Workflows and Tools panels.
- Check that the manifest year matches the running Revit year.
- Check the bridge log at `%APPDATA%\AECModelBridge\Logs\bridge.jsonl`.
- Only if you turned on legacy mode (`MCP_REVIT_LEGACY_PORT=1`): confirm no other program is using port `3000`. The default mode picks a free port by itself.

### Add-in build fails

- Run `dotnet --list-sdks` and confirm the required SDK is installed.
- For Revit 2024, install the .NET Framework 4.8 developer pack.
- Confirm the selected `-RevitVersion` is one of `2024`, `2025`, `2026`, or
  `2027`.
- If Revit is not installed on the build machine, the build uses the matching
  Revit API reference packages.

### Workspace access denied

- Use absolute paths for `MCP_REVIT_WORKSPACE_DIR`.
- List every folder you need in `MCP_REVIT_ALLOWED_DIRECTORIES`.
- Separate several Windows paths with semicolons.

For more settings, see the [configuration reference](configuration-reference.md)
and the [security guide](security.md).
