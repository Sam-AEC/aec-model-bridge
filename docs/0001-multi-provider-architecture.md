# ADR 0001: Multi-Provider AEC Automation Architecture

## Status
Accepted

## Context
The AEC Model Bridge is being expanded from a Revit-only MCP bridge to a multi-platform AEC automation platform. To accommodate diverse software systems (e.g., Rhino, Tekla, Archicad, IfcOpenShell, Autodesk Forma, Speckle) while maintaining existing Revit tools and compatibility, we need a unified provider architecture.

## Decisions

### 1. Provider Discovery and Registry
- **Headless & In-Process Providers**: Registered directly in a Python `ProviderRegistry` class.
- **Local Desktop Adapters**: Discoverable dynamically via local loopback ports. Desktop adapters will bind to dynamic loopback ports and register their active endpoint, process ID, and a security bearer token with a local registry.
- **Cloud Providers**: Discovered and loaded dynamically based on environment configuration or user credentials.

### 2. Transport Types
- **Headless/Local Files**: In-process Python imports (e.g., `IfcOpenShell`) for zero overhead and deterministic executions.
- **Desktop SDKs**: Isolated process HTTP/JSON-RPC boundaries over loopback (e.g., Revit bridge). This isolates non-redistributable SDKs and prevents C# crashes from bringing down the MCP server.
- **Cloud Integrations**: Secure HTTPS REST/GraphQL protocols.
- **Batch/Compute Engines**: Asynchronous HTTP/WebSocket queues with job status polling.

### 3. Capability Manifests
Each provider publishes a runtime capability manifest:
```json
{
  "provider_id": "ifc",
  "tools": [
    {
      "name": "ifc_get_metadata",
      "description": "Read file headers and schemas...",
      "input_schema": { ... },
      "output_schema": { ... },
      "is_mutating": false,
      "confirmation_required": false,
      "execution_mode": "sync"
    }
  ]
}
```
The MCP server aggregates these manifests dynamically rather than hardcoding tool names.

### 4. Object References
Instead of designing a universal BIM object model, we use a flexible reference envelope that preserves native identities:
```json
{
  "provider": "ifc",
  "project_id": null,
  "model_id": "structure.ifc",
  "object_id": "12345",
  "stable_id": null,
  "ifc_guid": "2XQ$n5SLP5MBLyL6JQj8Z0",
  "version": "v1"
}
```
Different platforms map object identities via standard fields like `ifc_guid` or external mapping tables.

### 5. Authentication and Security
- **Desktop/Local**: Every local desktop bridge generates a random per-session bearer token (nonce) during startup. The client must supply this token in authorization headers. Loops back only to `127.0.0.1`.
- **Cloud (OAuth)**: Credentials must never appear in tool parameters, results, or logs. Use OS-level secure credential stores or environment variables loaded into the server environment. OAuth code flow with PKCE is used for user-delegated access.

### 6. Mutation Controls
- Mutating tools support a `dry_run` parameter where applicable.
- Confirmations are requested before high-risk mutations.
- Transacted operations are wrapped in host transaction APIs (e.g., Revit transactions) to support undo.
- Idempotency keys are included for cloud operations.

### 7. Asynchronous Jobs
Long-running or batch operations yield a job reference:
```json
{
  "job_id": "job_9876",
  "status": "running",
  "progress_percent": 45,
  "artifacts": []
}
```
Clients poll or receive webhooks, with support for cancellation.

### 8. Licensing Boundaries
- Host SDK binaries (e.g., Autodesk Revit assemblies, RhinoCommon, Tekla Open API) must remain separate from the core repository.
- Code dependencies utilize standard interfaces. Connectors are packaged separately.
- Clear licensing boundaries apply (GPL/LGPL linking exemptions where required).

### 9. Compatibility and Legacy Support
- Existing `revit_*` tool names, routes, and `MCP_REVIT_` configuration are preserved.
- A Revit Compatibility Adapter maps legacy MCP calls directly to the new `RevitProvider`.
- Legacy configuration is mapped to provider configuration automatically.

## Consequences
- **Extensibility**: Adding a new AEC integration only requires writing a class that conforms to the `AECProvider` interface.
- **Robustness**: In-process libraries like `IfcOpenShell` do not require desktop software to run or test.
- **Isolation**: Prohibits licensing leakage and maintains strict desktop SDK process isolation.
