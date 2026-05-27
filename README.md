<div align="center">

<img src="https://cdn.simpleicons.org/autodeskrevit/0696D7" alt="Revit" height="80"/>

# Autodesk Revit MCP Server

**Model Context Protocol server for Autodesk Revit**

[![License: MIT](https://img.shields.io/badge/License-MIT-0078D4?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![.NET](https://img.shields.io/badge/.NET-4.8-512BD4?style=flat-square&logo=dotnet)](https://dotnet.microsoft.com)
[![Revit](https://img.shields.io/badge/Revit-2024--2026-0696D7?style=flat-square)](https://autodesk.com/products/revit)

[Quick Start](#quick-start) | [API Reference](docs/tools.md)

</div>

---

## Overview

Production-ready MCP server enabling AI agents to control Autodesk Revit through natural language. Integrates with Claude Desktop, Microsoft Copilot, and custom MCP clients.

**Key Features:**

- 100+ Revit API tools (geometry, views, sheets, families, MEP, structures)
- Localhost HTTP bridge with sub-second response time
- Thread-safe ExternalEvent architecture
- Advanced reflection API for unlimited Revit access
- Production-ready with comprehensive tool coverage

## Quick Start

### Prerequisites

- Windows 10/11
- Autodesk Revit 2024-2026
- Python 3.11+
- .NET Framework 4.8

### Installation

```powershell
# Clone repository
git clone https://github.com/Sam-AEC/Autodesk-Revit-MCP-Server.git
cd Autodesk-Revit-MCP-Server

# Build Revit add-in
.\scripts\build-addin.ps1 -RevitVersion 2024

# Install Python package
pip install -e packages/mcp-server-revit
```

### Configure Claude Desktop

Edit `%APPDATA%\Claude\claude_desktop_config.json`:

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

### Configure VS Code / GitHub Copilot

This repository includes a workspace MCP config at `.vscode/mcp.json`. After installing the Python package and starting Revit with the bridge add-in loaded, open this repository in VS Code and run `MCP: List Servers` or use the MCP Servers view.

### Verify Installation

Start Revit, then:

```powershell
curl http://localhost:3000/health
```

Expected response:
```json
{
  "status": "healthy",
  "revit_version": "2024"
}
```

---

## Architecture

```
┌─────────────────────────────────┐
│ AI Client (Claude/Copilot)      │
└───────────────┬─────────────────┘
                │ MCP Protocol
┌───────────────▼─────────────────┐
│ MCP Server (Python)             │
│ - Tool Registry                 │
│ - Security/Audit                │
└───────────────┬─────────────────┘
                │ HTTP :3000
┌───────────────▼─────────────────┐
│ Revit Bridge Add-in (C#)        │
│ - HTTP Server                   │
│ - ExternalEvent Handler         │
└───────────────┬─────────────────┘
                │ Revit API
┌───────────────▼─────────────────┐
│ Autodesk Revit 2024-2026        │
└─────────────────────────────────┘
```

**Threading Model:** HTTP requests are queued and executed on Revit's main thread via `ExternalEvent` for thread safety.

**Bridge Status:** The bridge runs as a localhost HTTP server on port 3000, providing health checks and tool execution endpoints.

---

## Available Tools

### Document Management
- `revit.create_new_document` - Create blank project
- `revit.open_document` - Open RVT/RFA file
- `revit.save_document` - Save active document
- `revit.close_document` - Close document
- `revit.get_document_info` - Get project metadata

### Levels & Grids
- `revit.create_level` - Create level at elevation
- `revit.list_levels` - List all levels
- `revit.create_grid` - Create grid line

### Model Elements
- `revit.create_wall` - Create wall from curve
- `revit.create_floor` - Create floor from profile
- `revit.create_roof` - Create roof from profile
- `revit.create_column` - Create structural column
- `revit.create_beam` - Create structural beam
- `revit.create_foundation` - Create foundation element
- `revit.create_room` - Create room boundary

### MEP Systems
- `revit.create_duct` - Create HVAC duct
- `revit.create_pipe` - Create plumbing pipe
- `revit.create_cable_tray` - Create cable tray
- `revit.create_conduit` - Create electrical conduit
- `revit.get_mep_systems` - List MEP systems

### Families & Components
- `revit.place_family_instance` - Place family instance
- `revit.place_door` - Place door in wall
- `revit.place_window` - Place window in wall
- `revit.list_families` - List loaded families
- `revit.edit_family` - Edit family document

### Element Operations
- `revit.delete_element` - Delete element
- `revit.copy_element` - Copy element with translation
- `revit.move_element` - Move element by vector
- `revit.rotate_element` - Rotate element around axis
- `revit.mirror_element` - Mirror element across plane
- `revit.pin_element` - Pin element in place
- `revit.unpin_element` - Unpin element

### Parameters
- `revit.get_element_parameters` - Read element parameters
- `revit.set_parameter_value` - Write parameter value
- `revit.get_parameter_value` - Read single parameter
- `revit.batch_set_parameters` - Batch update parameters
- `revit.get_type_parameters` - Get type parameters
- `revit.set_type_parameter` - Set type parameter

### Views
- `revit.create_3d_view` - Create isometric 3D view
- `revit.create_section_view` - Create section view
- `revit.create_floor_plan_view` - Create floor plan
- `revit.duplicate_view` - Duplicate view
- `revit.apply_view_template` - Apply view template
- `revit.get_view_templates` - List view templates
- `revit.list_views` - List all views

### Sheets & Documentation
- `revit.create_sheet` - Create sheet with titleblock
- `revit.place_viewport_on_sheet` - Place viewport on sheet
- `revit.list_sheets` - List all sheets
- `revit.delete_sheet` - Delete sheet
- `revit.duplicate_sheet` - Duplicate sheet
- `revit.get_sheet_info` - Get sheet information
- `revit.list_titleblocks` - List titleblock types
- `revit.populate_titleblock` - Fill titleblock parameters
- `revit.renumber_sheets` - Renumber sheets
- `revit.batch_create_sheets_from_csv` - Create sheets from CSV

### Annotation
- `revit.create_tag` - Create element tag
- `revit.create_dimension` - Create dimension
- `revit.create_text_note` - Create text annotation
- `revit.create_text_type` - Create text type
- `revit.tag_all_in_view` - Tag all elements in view
- `revit.create_revision_cloud` - Create revision cloud

### Selection & Query
- `revit.get_selection` - Get current selection
- `revit.set_selection` - Set element selection
- `revit.list_elements_by_category` - Query by category
- `revit.get_element_type` - Get element type
- `revit.get_element_bounding_box` - Get element bounds
- `revit.get_categories` - List all categories

### Groups & Links
- `revit.create_group` - Create model group
- `revit.ungroup` - Ungroup elements
- `revit.convert_to_group` - Convert to group
- `revit.get_group_members` - Get group members
- `revit.get_link_instances` - List link instances
- `revit.get_rvt_links` - List Revit links

### Schedules & Data
- `revit.create_schedule` - Create schedule view
- `revit.get_schedule_data` - Extract schedule data
- `revit.export_schedules` - Export schedules to CSV
- `revit.calculate_material_quantities` - Calculate quantities

### Export Operations
- `revit.export_pdf_by_sheet_set` - Export to PDF
- `revit.export_dwg_by_view` - Export to DWG
- `revit.export_ifc_with_settings` - Export to IFC
- `revit.export_navisworks` - Export to Navisworks
- `revit.export_image` - Export view as image
- `revit.render_3d_view` - Render 3D view

### Project Information
- `revit.get_phases` - List project phases
- `revit.get_phase_filters` - List phase filters
- `revit.get_design_options` - List design options
- `revit.get_worksets` - List worksets
- `revit.get_warnings` - Get model warnings
- `revit.get_project_location` - Get project location

### Worksharing
- `revit.sync_to_central` - Synchronize with central
- `revit.relinquish_all` - Relinquish all elements

### Materials & Rendering
- `revit.create_material` - Create material
- `revit.set_element_material` - Assign material
- `revit.get_render_settings` - Get render settings

### Analysis & Validation
- `revit.check_clashes` - Run clash detection
- `revit.get_room_boundary` - Get room boundary

### Advanced Features
- `revit.invoke_method` - Universal Revit API method invocation
- `revit.reflect_get` - Get property via reflection
- `revit.reflect_set` - Set property via reflection

**Total: 100+ tools** • **Full API Reference:** [docs/tools.md](docs/tools.md)

---

## Project Structure

```
Autodesk-Revit-MCP-Server/
├── packages/
│   ├── revit-bridge-addin/       # C# Revit Add-in
│   │   └── src/Bridge/
│   │       ├── App.cs            # IExternalApplication
│   │       ├── BridgeServer.cs   # HTTP server
│   │       └── BridgeCommandFactory.cs
│   └── mcp-server-revit/         # Python MCP Server
│       ├── src/revit_mcp_server/
│       │   ├── mcp_server.py     # MCP protocol
│       │   ├── bridge/client.py  # HTTP client
│       │   └── tools/            # Tool handlers
│       └── tests/
├── scripts/
│   ├── build-addin.ps1           # Build C# DLL
│   └── install.ps1               # Deploy to Revit
├── docs/
│   └── tools.md                  # API reference listing
└── README.md
```

---

## Documentation

- [API Reference (Revit MCP Tools List)](docs/tools.md)

---

## License

[MIT License](LICENSE) - Copyright (c) 2025

---

## Links

- [Issues](https://github.com/Sam-AEC/Autodesk-Revit-MCP-Server/issues)
- [Discussions](https://github.com/Sam-AEC/Autodesk-Revit-MCP-Server/discussions)
- [Model Context Protocol](https://modelcontextprotocol.io)

---

<div align="center">

**[⬆ Back to Top](#revit-mcp-server)**

</div>
