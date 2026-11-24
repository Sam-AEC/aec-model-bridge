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

## Run the server with uvx

[uv](https://docs.astral.sh/uv/getting-started/installation/) can fetch and start
the MCP server from this repository without a clone. This works today, without a
PyPI release:

```bash
uvx --from "git+https://github.com/Sam-AEC/aec-model-bridge#subdirectory=packages/mcp-server-revit" aec-model-bridge
```

The server speaks MCP over stdin and stdout, so you normally put this command in
your client configuration instead of running it in a terminal (see
[one-click install links](#one-click-install-links)). Set `MCP_REVIT_MODE=mock`
to try it without Revit. Live use still needs the Revit add-in, from the installer
or the source install above.

After the first PyPI release, the short form will be:

```bash
uvx aec-model-bridge
```

The package is not on PyPI yet, so the short form does not work today.

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

## One-click install links

Each link adds the same server entry (`uvx`, mode `bridge`). No directory variables are needed. The workspace defaults to `~/Documents/AEC Model Bridge`. They need `uv` only.

```json
{"command":"uvx","args":["--from","git+https://github.com/Sam-AEC/aec-model-bridge#subdirectory=packages/mcp-server-revit","aec-model-bridge"],"env":{"MCP_REVIT_MODE":"bridge"}}
```

Regenerate or check the links with `python scripts/make_install_links.py` (`--json`, `--check`). `tests/test_install_links.py` decodes each link and compares it with the entry above.

### VS Code

Format: `vscode:mcp/install?` followed by `encodeURIComponent(JSON.stringify({name, ...server}))`. Insiders uses `vscode-insiders:mcp/install?`.

```text
vscode:mcp/install?%7B%22name%22%3A%22aec-model-bridge%22%2C%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22--from%22%2C%22git%2Bhttps%3A%2F%2Fgithub.com%2FSam-AEC%2Faec-model-bridge%23subdirectory%3Dpackages%2Fmcp-server-revit%22%2C%22aec-model-bridge%22%5D%2C%22env%22%3A%7B%22MCP_REVIT_MODE%22%3A%22bridge%22%7D%7D
```

Command line (bash or cmd quoting):

```text
code --add-mcp "{\"name\":\"aec-model-bridge\",\"command\":\"uvx\",\"args\":[\"--from\",\"git+https://github.com/Sam-AEC/aec-model-bridge#subdirectory=packages/mcp-server-revit\",\"aec-model-bridge\"],\"env\":{\"MCP_REVIT_MODE\":\"bridge\"}}"
```

GitHub strips `vscode:` and `cursor:` hrefs from Markdown, so the README badge links here. The `vscode.dev/redirect/mcp/install` form is undocumented and returned HTTP 403 for values containing `#subdirectory=` when tested. A PyPI release would allow a plain `uvx aec-model-bridge` entry.

### Cursor

```text
cursor://anysphere.cursor-deeplink/mcp/install?name=aec-model-bridge&config=<base64 of the server entry above>
```

The README badge uses `https://cursor.com/en/install-mcp?name=aec-model-bridge&config=<same base64>` because GitHub strips `cursor:` links. That https form is UNVERIFIED: it is not in the Cursor docs.

### Claude Desktop

The release workflow attaches a `.mcpb` bundle. Download it from the [latest release](https://github.com/Sam-AEC/aec-model-bridge/releases/latest) and open it.

## First check after install

Open a project in Revit and open the panel from the AEC Bridge tab. The Setup check card runs on load. `Ready` means all checks passed. Otherwise each failing check shows what to do; fix it and press Refresh. See [troubleshooting](troubleshooting.md#panel-setup-check) for each check.

Without Revit, mock mode (below) returns a small sample model: two levels, one wall, one door, two rooms. Write tools return `mock-response` and change nothing. A first prompt that works: "Which AEC Model Bridge tools do you have?". Then `model_inspector_summarize_model`, then `qaqc_checker_run_check` with the `core` pack. To try the gate in mock mode, draft a change with `plan_actions`, then approve it yourself with `aec-model-bridge-approve show <plan_id>` and `aec-model-bridge-approve approve <plan_id>` in a terminal that uses the same workspace as the client. The assistant cannot call `approve_plan` or `reject_plan`.

## Update and uninstall

Close Revit before running a newer installer or uninstalling. Remove the MCP client entry yourself. The workspace holds project data and is kept. After install the server and add-in run offline; AI providers and optional cloud tools (Speckle, Autodesk) need network access.

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

## Supported start command

The supported way to start the server is `python.exe -m revit_mcp_server` (the bundled one is `C:\ProgramData\AECModelBridge\python\python.exe`). `-m revit_mcp_server.mcp_server` is the same server and also works. The installer's client setup writes `python.exe -m revit_mcp_server.mcp_server`.

The bundle also has relocatable launchers `python\Scripts\aec-model-bridge.cmd`, `revit-mcp-server.cmd`, `aec-model-bridge-panel-server.cmd` and `aec-model-bridge-approve.cmd`. They call `python.exe` next to them, so they keep working if the folder moves. Releases before the fix for issue #159 shipped pip `.exe` launchers in that folder; those exit silently on a user PC. Do not point a client at an `.exe` in `python\Scripts`.

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
