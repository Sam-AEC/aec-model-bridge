# Security Model

AEC Model Bridge implements a defense-in-depth security model to protect local models and filesystems from unauthorized or destructive actions by AI agents. The security posture relies on strict trust boundaries, local loopback restrictions, workspace sandboxing, input schema validation, and structured audit logs.

---

## 1. Trust Boundaries & Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  External client / LLM Agent (Untrusted)                    │
└─────────────────────┬───────────────────────────────────────┘
                      │ MCP Protocol (stdio JSON-RPC)
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  Unified Python MCP Server (Router)                         │
│  - Configures environment & paths                           │
│  - Enforces workspace sandbox via WorkspaceMonitor          │
│  - Redacts sensitive logs & captures audits                 │
│  - Routes tool calls to in-process or loopback providers    │
└──────────┬──────────┬──────────┬──────────┬──────────┬──────┘
           │          │          │          │          │
   Local C#│   Local C#│  Headless│  In-Proc │   Cloud  │
   Bridge  │   Bridge  │  IFC     │  Helper  │   OAuth  │
   (:3000) │   (:3004) │  (Python)│  (SQLite)│  (HTTPS) │
           ▼          ▼          ▼          ▼          ▼
┌──────────┐┌─────────┐┌─────────┐┌─────────┐┌──────────┐
│  Revit   ││  Rhino  ││ IfcOpen ││ AEC     ││ Speckle  │
│  Add-in  ││  Bridge ││ Shell   ││ Mapper  ││ & APS    │
└──────────┘└─────────┘└─────────┘└─────────┘└──────────┘
```

The system coordinates several platform providers:
1. **Unified Python MCP Server**: The central gateway. Runs locally, communicates via standard input/output (stdio) with the LLM host.
2. **Revit Add-in**: Runs in-process inside Revit. Exposes a local HTTP port.
3. **Rhino Bridge Add-in**: Runs in-process inside Rhino. Exposes HTTP port 3004.
4. **IFC Parsing**: Executed in-process via `IfcOpenShell` (headless Python).
5. **Speckle & APS Cloud Connections**: Connect to external APIs over HTTPS using OAuth-PKCE.

---

## 2. Network Security & Local Boundary

To prevent remote exploitation, all desktop bridges bind strictly to the loopback address.

### Localhost Boundary
- Add-ins bind exclusively to `127.0.0.1` (localhost).
- They will reject external incoming connections.
- They must **never** be exposed via public reverse proxies or port-forwarding.

### Authentication Modes (Revit Add-in)
The C# Revit bridge supports two runtime modes:
1. **Legacy Mode (Default)**: Binds to fixed port `3000` with no authentication (relies entirely on the localhost boundary). Enabled by default unless configured otherwise.
2. **Contract v2 Mode**: Runs with dynamic loopback ports and bearer token authorization. A random per-session bearer token (nonce) is generated at startup and written to local registry files. The Python MCP provider reads the registry file, obtains the port and token, and uses authorization headers for subsequent requests.

---

## 3. Workspace Sandboxing

All local filesystem activities (file reads, database exports, sheet prints) are sandboxed to explicitly configured directories.

### Configuration
The sandboxing behavior is driven by the following environment variables:

| Environment Variable | Python Config Field | Description |
|---|---|---|
| `MCP_REVIT_WORKSPACE_DIR` | `workspace_dir` | The default directory for writing outputs and log files. |
| `MCP_REVIT_ALLOWED_DIRECTORIES` | `allowed_directories` | A semicolon-delimited (`;`) list of allowed directories. |

### Enforcement
The `WorkspaceMonitor` class validates every path candidate before any filesystem operation:

```python
from pathlib import Path
from revit_mcp_server.security.workspace import WorkspaceMonitor

# Initialize with allowed paths
monitor = WorkspaceMonitor(allowed_directories=[Path("C:\\RevitProjects"), Path("C:\\exports")])

# Safe Path
safe_path = monitor.assert_in_workspace(Path("C:\\RevitProjects\\model.rvt"))  # Returns resolved Path

# Unsafe Path - Raises WorkspaceViolation
unsafe_path = monitor.assert_in_workspace(Path("C:\\Windows\\System32\\cmd.exe"))
```

### Path Traversal Guard
The `WorkspaceMonitor` resolves candidate paths to absolute, canonical paths:
- Resolves all symbolic links.
- Evaluates relative path elements (`..`, `.`).
- Asserts that the target resolved path is relative to one of the configured allowed directories (`path.is_relative_to(allowed_dir)`).

---

## 4. Input Validation & Schema Integrity

All tool arguments are validated before passing them to backend providers.
- **Pydantic Validation**: Every MCP tool has an associated Pydantic schema defining required parameters, strict data types, and value constraints.
- **Malformed Input Rejection**: Inputs violating schemas are rejected immediately by the Python server, preventing malformed inputs from reaching the C# API thread.

---

## 5. Audit Logging & Sensitive Data Redaction

Every tool call (successful or failed) is recorded chronologically to an append-only audit trail.

### Log Configuration
- Configured via `MCP_REVIT_AUDIT_LOG` (defaults to `audit.log` in the working directory).
- Controlled by `MCP_REVIT_LOG_LEVEL` (defaults to `INFO`).

### Redaction Rules
To prevent sensitive tokens, OAuth codes, and local directories from leaking into log files or LLM context windows, the `AuditRecorder` runs a recursive redaction step:
- **Sensitive Keys**: Fields matching password, token, api_key, authorization, secret, client_secret, or auth codes are replaced with `<redacted>`.
- **System Paths**: File path strings (both Windows and POSIX) are matched against regex patterns and replaced with `<redacted-path>`.

Example serialized log entry:
```json
{
  "timestamp": "2026-07-08T18:02:10.123456Z",
  "tool": "revit.export_schedule",
  "request_id": "req_abc123",
  "payload": {
    "document_path": "<redacted-path>",
    "schedule_name": "Door Schedule",
    "output_dir": "<redacted-path>"
  },
  "response": {
    "success": true,
    "output_path": "<redacted-path>"
  }
}
```

---

## 6. Threat Model & Safety Checklist

### In-Scope Guards
- Path traversal exploits trying to read sensitive configuration or files.
- Unauthorized cloud calls (credentials stored out-of-band in env vars/keyrings).
- Malformed C# call execution leading to Revit process crashes (prevented by process boundary and input schema validation).

### Out-of-Scope (Host Machine Security)
- Local network compromises (e.g. malicious software running on the same loopback).
- Unauthorized physical access or user-level malware.
- Vendor API bugs (Autodesk Revit, Rhino).

### Safety Checklist
- [ ] Ensure `MCP_REVIT_WORKSPACE_DIR` is set to a dedicated folder.
- [ ] Limit `MCP_REVIT_ALLOWED_DIRECTORIES` to only the required assets.
- [ ] Confirm no bridge is configured to bind to `0.0.0.0` or shared port-forward.
- [ ] Secure access permissions for the audit log path (`audit.log`).
