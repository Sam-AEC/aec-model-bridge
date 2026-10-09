# Security model

AEC Model Bridge uses several layers to protect your models and files from unwanted or destructive actions by AI agents. The layers are: clear trust boundaries, loopback-only connections, a workspace sandbox, input checks, an approval step for changes, and audit logs.

---

## 1. Trust boundaries and architecture

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

The Revit add-in listens on port `3000` only in legacy mode. In the default mode it picks a dynamic port (see section 2).

The system has these parts:
1. **Unified Python MCP server**: the central gateway. It runs on your machine and talks to the AI client over standard input and output (stdio).
2. **Revit add-in**: runs inside Revit and opens a local HTTP port.
3. **Rhino bridge add-in**: runs inside Rhino and opens HTTP port 3004.
4. **IFC parsing**: runs inside the Python server with `IfcOpenShell`. Revit is not needed.
5. **Speckle and APS cloud connections**: call external APIs over HTTPS with OAuth-PKCE.

---

## 2. Network security and the local boundary

All desktop bridges listen on the loopback address only.

### Localhost boundary
- Add-ins bind to `127.0.0.1` (localhost) only.
- They reject connections from other machines.
- Never expose them through a public reverse proxy or port forwarding.

### Authentication modes (Revit add-in)
The C# Revit bridge has two modes:
1. **Contract v2 mode (default)**: the add-in picks a dynamic loopback port and creates a random bearer token each session. It writes both to a local registry file. The Python MCP server reads that file and sends the token with every request.
2. **Legacy mode (opt-in)**: set the add-in's environment variable `MCP_REVIT_LEGACY_PORT` to `true` or `1`. The add-in then binds to fixed port `3000` with no authentication and relies only on the localhost boundary. Use it only if an older client needs it.

---

## 3. Workspace sandboxing

All local file work (file reads, database exports, sheet prints) stays inside the configured directories.

### Configuration
Two environment variables control the sandbox:

| Environment variable | Python config field | Description |
|---|---|---|
| `MCP_REVIT_WORKSPACE_DIR` | `workspace_dir` | The default directory for generated files. Defaults to `~/Documents/AEC Model Bridge`. |
| `MCP_REVIT_ALLOWED_DIRECTORIES` | `allowed_directories` | A list of allowed directories, separated by semicolons (`;`). Defaults to the workspace directory only. |

### Enforcement
The `WorkspaceMonitor` class checks every path before any file operation:

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

### Path traversal guard
The `WorkspaceMonitor` turns each path into an absolute, canonical path. It then:
- Follows all symbolic links.
- Resolves relative parts (`..`, `.`).
- Checks that the result sits inside one of the allowed directories (`path.is_relative_to(allowed_dir)`).

---

## 4. Input validation and schema integrity

The server checks all tool arguments before it passes them to a provider.
- **Pydantic validation**: every MCP tool has a Pydantic schema. It sets the required parameters, data types and value limits.
- **Rejecting bad input**: the Python server rejects input that breaks the schema. Bad input does not reach the C# API thread.

---

## 5. Audit logging and sensitive data redaction

The audit recorder writes one line per tool call to an append-only file. See [Logging and audit](logging-and-audit.md) for what each log covers and for a caveat about which server writes the file.

### Log configuration
- Set the file with `MCP_REVIT_AUDIT_LOG`. The default is `audit.log` in the working directory of the server process.
- Set the level with `MCP_REVIT_LOG_LEVEL`. The default is `INFO`.

### Redaction rules
Audit entries and tool responses pass through a redaction step. It keeps tokens, OAuth codes and local directories out of log files and out of the AI's context:
- **Sensitive keys**: fields such as password, token, api_key, authorization, secret, client_secret and auth codes become `<redacted>`.
- **System paths**: Windows, UNC and POSIX file paths become `<redacted-path>`.

Example log entry:
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

## 6. Threat model and safety checklist

### What the design guards against
- Path traversal that tries to read sensitive files or settings.
- Unauthorized cloud calls. Credentials stay outside the tool arguments, in environment variables or keyrings.
- Malformed input that could crash Revit. The process boundary and input schemas prevent it.

### What is out of scope (host machine security)
- Other software on the same machine that can reach the loopback port.
- Physical access to the machine, and malware running as your user.
- Bugs in vendor APIs (Autodesk Revit, Rhino).

### Safety checklist
- [ ] Set `MCP_REVIT_WORKSPACE_DIR` to a dedicated folder.
- [ ] Limit `MCP_REVIT_ALLOWED_DIRECTORIES` to the folders you need.
- [ ] Confirm no bridge listens on `0.0.0.0` or sits behind a port forward.
- [ ] Restrict access to the audit log file (`audit.log` by default).
- [ ] Keep `MCP_REVIT_APPROVAL_MODE` at `required`, so every model change needs an approved plan.
