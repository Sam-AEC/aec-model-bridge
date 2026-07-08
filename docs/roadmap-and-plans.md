# AEC Model Bridge - Strategic Roadmap & Architecture Thesis

This document outlines the core engineering thesis, historical progress, and future roadmap of the **AEC Model Bridge** platform developed on the `development` branch.

## 🔗 Product Backlog & Plan References
For the buildable scaffolding plan and product vision details, see:
- [AEC Model Bridge Product Vision](file:///c:/Users/sammo/OneDrive/Documenten/GitHub/Autodesk-Revit-MCP-Server/docs/product/AEC_MODEL_BRIDGE_PRODUCT_VISION.md)
- [Scaffolding Task List (Phase Backlog)](file:///c:/Users/sammo/OneDrive/Documenten/GitHub/Autodesk-Revit-MCP-Server/docs/product/SCAFFOLDING_TASK_LIST.md)
- [MVP Execution Plan](file:///c:/Users/sammo/OneDrive/Documenten/GitHub/Autodesk-Revit-MCP-Server/docs/product/MVP_EXECUTION_PLAN.md)

---

## 💡 The Core Thesis

### The Problem in AEC Today
The Architecture, Engineering, and Construction (AEC) industry is historically fragmented. Structural design occurs in **Rhino/Grasshopper**, detail modeling in **Autodesk Revit**, data analysis in **IFC/Power BI**, and coordination in cloud Common Data Environments (CDEs) like **Speckle** or **Autodesk Construction Cloud (ACC)**. 
AI agents trying to interact with building models are typically blocked by:
1. Application-specific APIs requiring desktop application lifetimes.
2. The absence of a unified protocol to query and coordinate models across formats.
3. Severe security concerns around local paths and cloud access credentials leaking in AI contexts.

### The Solution: A Unified, Secure AEC MCP Runtime
The **AEC Model Bridge** solves this by wrapping all application contexts into a single, standardized Model Context Protocol (MCP) server. By routing tool queries through a dynamic provider registry, we enable AI and programmatic scripts to edit, audit, and orchestrate BIM data across boundaries.

---

## 🛠️ What Has Been Done (Historical Progress)

Since branching onto `development`, we have built the platform end-to-end:

### Phase 1 & 2: Modular Architecture Foundation
- **Unified Provider Registry (`base.py`, `registry.py`)**: Extracted the Revit-only bridge into a generic registry where multiple independent providers (IFC, Rhino, Revit, cloud CDEs) can register and expose capabilities.
- **Legacy Revit Adaptation (`revit.py`)**: Migrated all 100+ native Revit tools into the registry while maintaining 100% backwards compatibility (supporting dot/underscore notations).
- **IfcOpenShell Provider (`ifc.py`)**: Integrated a headless, read-only Python IFC parser for spatial hierarchy, unit summaries, and geometric bounding box querying.
- **Identity & Path Mapper (`identity_mapper.py`)**: Implemented deterministic GUID to buildingSMART IfcGUID compression/decompression, custom relational mapping links, and workspace-relative path resolution.

### Phase 3, 4, & 5: Advanced Engineering Workflows (COMPLETED)
- **Rhino/Compute & Proxy Connector (`rhino.py`, `proxy.py`)**: Built an async provider for `Rhino.Compute` web server, AND a dynamic `McpProxyProvider` over SSE that proxies an active Rhino MCP server (e.g. `localhost:9876`) directly into the unified AEC Model Bridge.
- **Topological Semantic Graph (`graph.py`)**: Implemented an in-memory `networkx` directed multi-graph mapping model elements as nodes and typing structural and adjacency relationships. Includes structural load path audits and AABB clash checks.
- **Navisworks Manage Bridge (`NavisworksBridge.dll`)**: Shipped a C# Add-in for Navisworks Manage (2024-2027) hosting its own local HTTP loop (`port 3002`) to allow MCP agents to query coordination/clash data dynamically.
- **OAuth-PKCE Cloud Sync & Speckle V3 (`cloud.py`, `speckle.py`)**: Integrated `specklepy` 3.x native support (`SpeckleProvider`) and `AutodeskDataProvider`. They handle secure authorization, branch/model querying, and pushing data directly to Power BI via Speckle Manager credentials, keeping tokens redacted.

### Orchestration, Redaction, & Loop Alignment (The Integration Phase)
- **Async Job Pipeline (`jobs.py`, `job_provider.py`)**: Built an async background queue manager. Calling any MCP tool with `run_async=True` returns a `JobReference` immediately and executes the tool in the background. Exposes `job_status` and `job_cancel` MCP tools.
- **Persistent Event-Loop Thread**: Structured the legacy synchronous `MCPServer` (`server.py`) to run a background daemon event-loop thread. Background jobs survive after individual synchronous tool-calls return.
- **Centralized Redaction (`audit.py`)**: Integrated a recursive data parser that redacts Windows/POSIX file paths and sensitive authentication credentials from all tool responses and audit logs.

---

## 🌅 The Strategic Horizon (Future Roadmap)

To maximize business value and align with standard corporate AEC workflows, the remaining platform evolution is structured into the following strategic phases:

### Phase C: Omni-Bridge Orchestrator & Flagship Recipes
- **Declarative Recipe Engine**: Support defining cross-tool workflows (e.g., Rhino massing → Revit instantiation → Navisworks clash) in YAML.
- **Run Records & Identity**: Emit versioned records of every orchestration run, linked through a unified identity map (IFC/Revit/Rhino GUIDs).
- **Flagship Workflows**: Prove end-to-end Concept-to-BIM, Coordination loops, and zero-switch Model Health audits.

### Phase D: Data Plane & Dashboards
- **Parquet/DuckDB Exporter**: Expose a tool to dump flattened parameters and graph relationships to local Parquet tables for secure, zero-licensing Power BI analysis.
- **Power BI Templates**: Ship `.pbit` templates over the lakehouse for Model Health and Coordination trends.
- **buildingSMART IDS**: Implement Information Delivery Specification (IDS) XML rule checking via the IfcOpenShell provider.
- **Automation Webhooks**: Support Slack/Teams webhooks on job completions.
- **Graph Exporters**: Export the semantic topological graph to `.graphml` for Neo4j visualization.

### Phase E: Wave 2 Switches
- **Excel**: Headless table read/write, dry-run diffing, and cloud variants via Microsoft Graph.
- **ACC/Forma**: AEC Data Model reads, issue publishing, and model-updated webhooks.
- **Solibri**: Integration for ruleset execution and BCF result extraction.

### Phase F: Platform, Distribution & Docs
- **Distribution**: End-to-end MkDocs site, zero-switch 10-minute tutorials, and automated release packaging for all switch variants.
- **SDK Templates**: Provide C# cookiecutter templates for authoring new desktop switches.

### Phase G: Wave 3 Adapter Specifications
- Prepare specifications for native integration into **Archicad, Tekla Structures, SketchUp, Bentley iTwin, Trimble Connect, and Procore**.

### Phase H: Any-AI Access Layer (Chapter 2)
- Provide access doors for non-developer BIM professionals, including:
  1. **Remote MCP (Streamable HTTP)** to plug directly into ChatGPT, Claude, and Copilot.
  2. **REST/OpenAPI Facade** for automation via Power Automate, Zapier, n8n.
  3. **BYO-LLM Console** with offline Ollama support.

### Phase I: Popularity Pack
- **BCF Provider**: Standalone BCF 2.1/3.0 read/write.
- **IFC-to-glTF**: Create self-contained HTML 3D viewers from IFC files.
- **LLM-Ready Digest**: Generate compressed markdown summaries of model state.
- **Automation Watchers**: Execute recipes automatically via drop-folder events.
