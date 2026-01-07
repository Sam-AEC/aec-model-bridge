<div align="center">

<img src="https://raw.githubusercontent.com/modelcontextprotocol/docs/main/logo/light.svg" alt="MCP Logo" width="120"/>

# Revit MCP Server

**Model Context Protocol server for Autodesk Revit automation**

Control Revit from AI agents, Python scripts, or any MCP-compatible client through a standardized interface.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![.NET Framework 4.8](https://img.shields.io/badge/.NET-4.8-512BD4?style=flat-square&logo=dotnet)](https://dotnet.microsoft.com/)
[![Revit 2020-2024](https://img.shields.io/badge/Revit-2020--2024-0696D7?style=flat-square)](https://www.autodesk.com/products/revit)

[Installation](#installation) • [Features](#features) • [Architecture](#architecture) • [Documentation](#documentation)

</div>

---

## Overview

This project provides a bridge between the Model Context Protocol (MCP) and Autodesk Revit, enabling programmatic control of Revit through a standardized API. It exposes 25 Revit operations for quality assurance, data extraction, and automation workflows.

**Key Components:**

- **MCP Server** (Python): Protocol handler with request validation, workspace sandboxing, and audit logging
- **Bridge Add-in** (C# .NET): Native Revit add-in that executes API calls via ExternalEvent
- **Mock Mode**: Standalone testing mode with deterministic responses (no Revit required)

**Use Cases:**

- Automated quality assurance in CI/CD pipelines
- AI-powered model analysis and reporting
- Batch data extraction and exports
- Integration with custom tooling and workflows

---

## Installation

### Prerequisites

**For Mock Mode (Testing/Development):**
- Python 3.11 or higher
- Git

**For Bridge Mode (Production with Revit):**
- Windows 10/11
- Autodesk Revit 2020-2024
- .NET Framework 4.8
- Visual Studio Build Tools or MSBuild

### Quick Start

#### 1. Clone and Install

```bash
git clone https://github.com/Sam-AEC/mcp.git
cd mcp
python -m venv venv
```

**Windows:**
```powershell
.\venv\Scripts\activate
```

**macOS/Linux:**
```bash
source venv/bin/activate
```

Install the MCP server:
```bash
pip install -e packages/mcp-server-revit[dev]
```

#### 2. Run in Mock Mode

```bash
# Set environment variables
export MCP_REVIT_MODE=mock
export WORKSPACE_DIR="$(pwd)/workspace"
mkdir -p workspace

# Run tests
pytest packages/mcp-server-revit/tests -v

# Start server (terminal 1)
python -m revit_mcp_server

# Run demo client (terminal 2)
python packages/client-demo/demo.py
```

#### 3. Run in Bridge Mode (Windows + Revit)

```powershell
# Build and install add-in
$env:REVIT_SDK = "C:\Program Files\Autodesk\Revit 2024\SDK"
.\scripts\build-addin.ps1
.\scripts\install-addin.ps1 -RevitYear 2024

# Start Revit, then configure and run server
$env:MCP_REVIT_MODE = "bridge"
$env:WORKSPACE_DIR = "C:\revit-workspace"
python -m revit_mcp_server
```

For detailed installation instructions, see [docs/install.md](docs/install.md).

---

## Features

### Available Tools (25)

| Category | Tools | Description |
|----------|-------|-------------|
| **Health Check** | `revit.health` | Server status and connectivity |
| **Document Management** | `open_document`, `list_views` | File operations and view enumeration |
| **Quality Assurance** | `model_health_summary`, `warning_triage`, `naming_standards`, `parameter_compliance`, `shared_params`, `view_templates`, `tag_coverage`, `room_completeness`, `link_monitor`, `coordinate_check` | Automated model validation and auditing |
| **Data Export** | `export_schedules`, `export_quantities`, `export_pdf`, `export_dwg`, `export_ifc` | Multi-format data extraction |
| **Sheet Management** | `batch_create_sheets`, `place_views_on_sheets`, `fill_titleblocks` | Sheet creation and configuration |
| **Baseline Tracking** | `export_baseline`, `diff_baseline` | Model comparison and change detection |

Full tool documentation: [docs/tools.md](docs/tools.md)

### Security Features

- **Workspace Sandboxing**: All file operations restricted to allowed directories
- **Schema Validation**: Pydantic-based request/response validation
- **Audit Logging**: JSONL logs with timestamps for all operations
- **Local-Only**: Bridge runs on localhost (no external network exposure)
- **Mock Mode**: Complete testing without Revit installation

Security model: [docs/security.md](docs/security.md)

---

## Architecture

```
┌─────────────────────┐
│   AI Agent/Client   │
│  (Claude, ChatGPT)  │
└──────────┬──────────┘
           │ MCP Protocol (stdio/SSE)
           ▼
┌─────────────────────┐
│   Python MCP Server │
│  - Validation       │
│  - Sandboxing       │
│  - Logging          │
└──────────┬──────────┘
           │ HTTP (localhost:3000)
           ▼
┌─────────────────────┐
│  C# Bridge Add-in   │
│  - ExternalEvent    │
│  - API Execution    │
└──────────┬──────────┘
           │ Revit API
           ▼
┌─────────────────────┐
│   Autodesk Revit    │
└─────────────────────┘
```

**Why this architecture?**

The Revit API requires:
- .NET Framework (C# code)
- Windows operating system
- UI thread execution via ExternalEvent

This bridge architecture handles the complexity while exposing a simple, cross-platform JSON interface via MCP.

Detailed architecture: [docs/architecture.md](docs/architecture.md)

---

## Usage Example

### Python Client

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Connect to MCP server
server_params = StdioServerParameters(
    command="python",
    args=["-m", "revit_mcp_server"],
    env={"MCP_REVIT_MODE": "bridge"}
)

async with stdio_client(server_params) as (read, write):
    async with ClientSession(read, write) as session:
        # Initialize
        await session.initialize()

        # Open document
        result = await session.call_tool(
            "revit.open_document",
            arguments={"file_path": "/workspace/project.rvt"}
        )

        # Run QA audit
        warnings = await session.call_tool(
            "revit.warning_triage_report",
            arguments={}
        )

        # Export data
        schedules = await session.call_tool(
            "revit.export_schedules",
            arguments={"output_dir": "/workspace/exports"}
        )
```

### AI Agent Integration

Configure in your MCP client (Claude Desktop, Continue, etc.):

```json
{
  "mcpServers": {
    "revit": {
      "command": "python",
      "args": ["-m", "revit_mcp_server"],
      "env": {
        "MCP_REVIT_MODE": "bridge",
        "WORKSPACE_DIR": "C:\\revit-workspace"
      }
    }
  }
}
```

The agent can then use natural language to control Revit:

```
User: "Check the hospital.rvt model for warnings and naming violations"

Agent: [calls revit.open_document with hospital.rvt]
       [calls revit.warning_triage_report]
       [calls revit.naming_standards_audit]
       [generates report with findings and recommendations]
```

---

## Development

### Project Structure

```
mcp/
├── packages/
│   ├── mcp-server-revit/     # Python MCP server
│   ├── revit-bridge-addin/   # C# Revit add-in
│   └── client-demo/          # Example client
├── scripts/                  # Build and deployment scripts
├── docs/                     # Documentation
└── examples/                 # Configuration examples
```

### Running Tests

```bash
# Python tests
pytest packages/mcp-server-revit/tests -v

# C# tests (requires Visual Studio)
dotnet test packages/revit-bridge-addin/RevitBridge.Tests
```

### Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

---

## Documentation

- **[Installation Guide](docs/install.md)**: Detailed setup for mock and bridge modes
- **[Tool Reference](docs/tools.md)**: Complete API documentation for all 25 tools
- **[Architecture](docs/architecture.md)**: System design and component interaction
- **[Security Model](docs/security.md)**: Trust boundaries and threat mitigation

---

## Roadmap

**Version 0.2**
- Complete Revit API implementation (replace stubs)
- Async HTTP client with connection pooling
- Enhanced error handling and recovery
- Performance benchmarks

**Future**
- Additional QA tools (clash detection, BIM validation)
- Dynamo script integration
- Navisworks export support
- BIM 360/ACC integration
- Multi-document operations

---

## License

This project is licensed under the MIT License - see [LICENSE](LICENSE) for details.

---

## Support

- **Issues**: [GitHub Issues](https://github.com/Sam-AEC/mcp/issues)
- **Discussions**: [GitHub Discussions](https://github.com/Sam-AEC/mcp/discussions)
- **Documentation**: [docs/](docs/)

---

<div align="center">

Built with the [Model Context Protocol](https://modelcontextprotocol.io)

**[⭐ Star this repo](https://github.com/Sam-AEC/mcp)** if you find it useful

</div>
