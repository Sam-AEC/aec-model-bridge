<div align="center">

<img src="assets/logo.svg" alt="AEC Model Bridge logo: an isometric model cube with a bridge arch" height="120">

# AEC Model Bridge: Revit MCP server

**An open-source Revit MCP server and AI assistant for Revit. It lets Claude, Codex and other Model Context Protocol clients read and edit BIM models, with you approving every change.**

[![MCP Registry](https://img.shields.io/badge/MCP_Registry-active-0F766E?style=flat-square)](https://registry.modelcontextprotocol.io/?q=io.github.Sam-AEC%2Faec-model-bridge)
[![License](https://img.shields.io/badge/license-GPLv3%2B%20%2F%20Commercial-2563EB?style=flat-square)](LICENSING.md)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Revit](https://img.shields.io/badge/Revit-2024--2027-0696D7?style=flat-square)](https://www.autodesk.com/products/revit/)

[Install](#install-the-revit-add-in) | [Connect a client](#connect-claude-desktop-to-revit) | [Tools](docs/tools-generated.md) | [Documentation](#documentation) | [Latest release](https://github.com/Sam-AEC/aec-model-bridge/releases/latest)

</div>

AEC Model Bridge is a Python MCP server plus a native Revit add-in. An AI
assistant such as Claude or Codex connects to the server, and the server runs
BIM automation tasks in the Revit model you have open. The same server also
reads IFC files, and it has providers for Rhino and Grasshopper, Speckle and
Navisworks.

It does not edit your model on its own. Any tool that changes the model goes
through a plan that you review and approve first. See
[How approval works](#how-approval-works).

**License:** GPL-3.0-or-later with a Revit linking exception, or a separate
commercial license ([details](LICENSING.md)). Independent project, not
affiliated with Autodesk.

## Quick start

For live Revit automation you need Windows, a licensed Revit 2024 to 2027,
Python 3.11 or newer, and the Revit add-in
([install steps](#install-the-revit-add-in)). Then add this to your
`claude_desktop_config.json` (Codex, Cursor and VS Code use the same values):

```json
{
  "mcpServers": {
    "aec-model-bridge": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/Sam-AEC/aec-model-bridge#subdirectory=packages/mcp-server-revit",
        "aec-model-bridge"
      ],
      "env": {
        "MCP_REVIT_MODE": "bridge",
        "MCP_REVIT_WORKSPACE_DIR": "C:\\RevitProjects",
        "MCP_REVIT_ALLOWED_DIRECTORIES": "C:\\RevitProjects"
      }
    }
  }
}
```

Want to look at the tools first, without Revit? Set `"MCP_REVIT_MODE": "mock"`.
The server then starts anywhere, lists every tool with its schema and returns
canned responses instead of touching a model. A `Dockerfile` for the same mock
mode is in the repository root (`docker build -t aec-model-bridge .`, then
`docker run -i --rm aec-model-bridge`).

### Tools at a glance

| Area | Tools | What they do |
| --- | --- | --- |
| Revit | 103 | Read the model, create and edit elements, parameters, views, sheets, schedules, exports, worksharing |
| Approval | 6 | Plan, review, approve, execute and roll back model changes |
| Modules | 34 | Snapshot inspection, parameter grids, QA/QC checks, recipes, reports, selections |
| Rhino and Grasshopper | 19 | Geometry, layers, materials, boolean operations |
| Speckle | 17 | Projects, models, versions, send and receive |
| Navisworks | 15 | Model tree, viewpoints, clash tests (in progress) |
| IFC | 7 | Read IFC files without Revit: structure, properties, validation |
| Graph, snapshots, exports, jobs | 18 | Semantic graph audits, snapshot diffs, SQLite export, background jobs |

219 tools are listed in the default setup (counts from the 1.3.1 server in mock
mode). The Autodesk Data tools appear when APS credentials are configured. The
[tool reference](docs/tools-generated.md) lists every tool. Each tool carries
MCP annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`,
`openWorldHint`), so clients can tell reads from writes.

### Demo

> TODO (owner): add a 30 to 60 second screen recording here as
> `assets/demo.gif` (or a linked video): ask Claude for a change, the plan
> appears in the Revit panel, you approve it, the model updates. No demo is
> shown until a real recording exists.

## What can the AI do in Revit?

The server exposes more than 200 tools across all providers. The full list is
in the [tool reference](docs/tools-generated.md). In Revit, the tools cover:

- **Reading the model:** list elements, categories, levels, views, sheets and
  families. Read element and type parameters, geometry, worksets, links,
  phases and warnings.
- **Editing parameters:** set one value, set values in batches, or set values
  for every element matching a filter. Create shared and project parameters.
- **Creating elements:** walls, floors, roofs, levels, grids, columns, beams,
  doors, windows, rooms, family instances, and some MEP elements such as ducts,
  pipes and conduit.
- **Documentation:** create views and sections, apply view templates, create
  and renumber sheets, place viewports, tag elements, add text notes and
  dimensions, and build schedules.
- **Exports:** IFC, DWG, images and Navisworks.
- **Checks and reports:** model snapshots and change diffs, a QA/QC checker,
  and report generation.

For anything the tool catalog does not cover, `invoke_method`, `reflect_get`
and `reflect_set` work with public Revit API members, and `execute_python`
runs IronPython inside Revit. These advanced tools have the same permissions as
the Revit process. Use them only with MCP clients and prompts you trust.

## How it works

The MCP client talks to one Python hub. The hub sends each call to the
provider that owns the tool. Providers for desktop apps talk to a small add-in
inside that app over localhost.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Sam-AEC/aec-model-bridge/main/docs/images/architecture-dark.png">
    <img src="https://raw.githubusercontent.com/Sam-AEC/aec-model-bridge/main/docs/images/architecture-light.png" alt="Architecture of AEC Model Bridge: an MCP client such as Claude or Codex calls the Python MCP hub, which routes tool calls to the Revit, Rhino, Navisworks, IFC and Speckle providers. The Revit and Rhino providers talk to add-ins over localhost HTTP, the IFC provider reads IFC files with IfcOpenShell, and Navisworks is still in progress." width="900">
  </picture>
</p>

<sub>Diagram source: [architecture.mmd](docs/diagrams/architecture.mmd). Regenerate the images with `python scripts/render_diagrams.py`.</sub>

Teal boxes work today. The amber dashed boxes are in progress. Indigo
shapes are data and external services.

### How approval works

The hub stops any tool call that changes the model unless it carries an
approved plan. The default mode is `required`. The AI proposes a plan, you
review it in the Revit side panel, and the add-in runs it on Revit's main
thread in a named transaction.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Sam-AEC/aec-model-bridge/main/docs/images/approval-flow-dark.png">
    <img src="https://raw.githubusercontent.com/Sam-AEC/aec-model-bridge/main/docs/images/approval-flow-light.png" alt="Approval flow: the AI assistant proposes a plan, the MCP hub and ApprovalGate show it in the Revit side panel, and only after you approve does execute_plan forward the commands to the Revit add-in, which runs them in one named transaction. If you reject or never approve, the call is blocked and the model stays untouched." width="900">
  </picture>
</p>

<sub>Diagram source: [approval-flow.mmd](docs/diagrams/approval-flow.mmd). Regenerate the images with `python scripts/render_diagrams.py`.</sub>

If a plan is approved and later turns out wrong, `rollback_plan` reverses it.
Rollback uses Revit Undo in the same session or inverse parameter values.
Operations that cannot be reversed, such as file output, ask for a second
confirmation. The lifecycle is in
[ADR 0008](docs/0008-approval-gate-lifecycle.md).

For unattended pipelines you can set `MCP_REVIT_APPROVAL_MODE=auto`. That turns
the human check off, so use it only in a controlled environment.

## Supported Revit versions

| Revit version | Add-in target | Build tools |
|---|---|---|
| 2024 | .NET Framework 4.8 | .NET 8 SDK and .NET Framework 4.8 developer pack |
| 2025 | .NET 8 for Windows | .NET 8 SDK |
| 2026 | .NET 8 for Windows | .NET 8 SDK |
| 2027 | .NET 10 for Windows | .NET 10 SDK |

You also need Windows 10 or 11, Python 3.11 or later, and a licensed Revit
installation for the version you use. Mock mode runs the server without Revit,
which is useful for development and tests.

### Other integrations

| Integration | Status |
|---|---|
| Revit | Available. Native C# add-in. |
| IFC (IfcOpenShell) | Available. Reads IFC files without Revit running. |
| Rhino and Grasshopper | Available. Connects to the Rhino add-in on `localhost:3004`. |
| Speckle | Available. Needs a Speckle client ID in your environment. |
| Navisworks Manage | In progress. The provider and its tools are registered. The Navisworks add-in is not finished. |
| Power BI | In progress. The provider and tool exist but are not registered in the hub. |
| Excel, Parquet and DuckDB | Planned. |

## Install the Revit add-in

You install two parts: the Python MCP server and the Revit add-in. Live Revit
automation needs both.

### 1. Install the MCP server

```powershell
git clone https://github.com/Sam-AEC/aec-model-bridge.git
cd aec-model-bridge

py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e packages/mcp-server-revit
```

### 2. Install the Revit add-in

Set the version to match your Revit installation. If Windows blocks the
downloaded scripts, right-click each `.ps1` file, open Properties, and select
Unblock before running them.

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

Each [GitHub release](https://github.com/Sam-AEC/aec-model-bridge/releases/latest)
has a ready-made package per Revit year, for example
`aec-model-bridge-revit-2026-<version>.zip`. Unzip it and run
`.\install.ps1 -RevitVersion 2026` instead of building from source. For a double-click
Windows installer, `scripts/build-installer.ps1` builds one with Inno Setup.
The full guide, with troubleshooting, is in [docs/install.md](docs/install.md).

## Connect Claude Desktop to Revit

Add the server to your MCP client configuration. For Claude Desktop, that is
the `mcpServers` section of `claude_desktop_config.json`. Codex, Cursor, VS
Code and other MCP clients use the same `command`, `args` and `env` values in
their own config format.

Use the Python executable from your virtual environment, and choose a workspace
folder the server may access:

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

Leave out `MCP_REVIT_HOST_VERSION` to target the newest open Revit instance.
Set it to a year such as `2024` or `2026` to lock a client entry to that Revit
version. `MCP_REVIT_BRIDGE_URL` overrides the endpoint for advanced setups.

VS Code users can start from [`.vscode/mcp.json`](.vscode/mcp.json). Hermes
Desktop users can start from [`Hermes.json`](Hermes.json) after replacing the
placeholder Python path. Clients that support MCP Bundles can install the
`.mcpb` file from the
[latest release](https://github.com/Sam-AEC/aec-model-bridge/releases/latest).
The Revit add-in is still required, because the server talks to the running
desktop application.

### Check the connection

Restart Revit after installing the add-in, open a model, and run:

```powershell
$registry = Get-ChildItem "$env:LOCALAPPDATA\AECModelBridge\registry\revit-*.json" | Select-Object -First 1
$switch = Get-Content $registry.FullName -Raw | ConvertFrom-Json
Invoke-RestMethod "$($switch.endpoint)/health"
```

The response should report `healthy` and the running Revit version. In Revit,
look for the `AEC Bridge` ribbon tab. Its Workflows panel has Open Panel,
Health Check, Pending Actions and Reports. Its Tools panel has Config, Help
and About.

## Security

- The Revit bridge listens on localhost only.
- The server reads and writes only inside the folders in
  `MCP_REVIT_ALLOWED_DIRECTORIES`.
- Mutating tools need an approved plan unless you turn approval off.
- Tool calls are written to an audit log, and secrets are redacted.

Details are in [docs/security.md](docs/security.md). To report a
vulnerability, follow [SECURITY.md](SECURITY.md).

## FAQ

### What is an MCP server for Revit?

The Model Context Protocol (MCP) is an open standard that lets AI assistants
call tools in other software. An MCP server for Revit publishes Revit
operations as tools. The assistant picks the tools, and the add-in runs them
inside Revit.

### Which AI assistants work with it?

Any MCP client that can start a local stdio server. We document Claude
Desktop, VS Code with GitHub Copilot, and clients that read a standard
`mcpServers` configuration. The panel chat can also use an Anthropic API key
or the `claude` or `codex` command-line tools if they are installed. See
[ADR 0012](docs/0012-native-agent-chat-backend.md).

### Can the AI change my model without asking?

Not in the default mode. Tools that change the model are blocked until a plan
is approved in the Revit panel. Read-only tools run without approval. If you
set `MCP_REVIT_APPROVAL_MODE=auto`, approval is skipped.

### Does it send my model to the cloud?

The server and the add-in run on your machine, and the bridge listens on
localhost. What the AI assistant sees depends on the client you use: the tool
results go to that client's model provider. Cloud-facing providers, such as
Speckle, only run when you configure them and call their tools.

### Does it work with IFC files without Revit?

Yes. The IFC provider reads files with IfcOpenShell. It can return file
metadata, the spatial structure, element properties and bounding boxes, run
queries by class, GUID, name or property, and validate the schema. It does
not edit IFC files.

### Can I use it without Revit installed?

You can run the server in mock mode for development and tests. Live model work
needs Revit 2024 to 2027 and the add-in.

## Releases and versions

AEC Model Bridge follows Semantic Versioning. Releases are tagged `vX.Y.Z` on
GitHub, and a root `VERSION` file holds the version number. See
[docs/versioning.md](docs/versioning.md) for the release process and
[CHANGELOG.md](CHANGELOG.md) for what changed in each version.

## Development

```powershell
# Python tests
python -m pytest packages/mcp-server-revit/tests

# Build one Revit version, for example 2026
.\scripts\build-addin.ps1 -RevitVersion 2026 -Configuration Release

# Build all supported versions
.\scripts\package.ps1 -RevitVersion All
```

CI builds the Python server and the add-in targets for Revit 2024 through 2027.
See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## Documentation

- [Installation guide](docs/install.md)
- [Tool reference](docs/tools-generated.md)
- [Architecture](docs/0001-multi-provider-architecture.md)
- [Configuration reference](docs/configuration-reference.md)
- [Security](docs/security.md)
- [MCP clients and registry](docs/marketplaces.md)
- [Versioning and releases](docs/versioning.md)
- [Contributing](CONTRIBUTING.md)
- [Contributors](CONTRIBUTORS.md)

## Project and license

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
