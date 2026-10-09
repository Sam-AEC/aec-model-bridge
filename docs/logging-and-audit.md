# Logging and audit

The project keeps two separate logs:

- the Python-side audit log
- the Revit add-in runtime log

## Python audit log

The code is in [packages/mcp-server-revit/src/revit_mcp_server/security/audit.py](../packages/mcp-server-revit/src/revit_mcp_server/security/audit.py).

`AuditRecorder.record()` writes one JSON line per tool call. Each line holds:

- a UTC timestamp
- the tool name
- the request ID
- the payload
- the response

Tokens, secrets and file paths are replaced before the line is written. See [Security](security.md). Set the file with `MCP_REVIT_AUDIT_LOG`. The default is `audit.log` in the working directory of the server process.

This log shows what the MCP server asked for.

Note: in the current code, only the legacy server (`legacy/server.py`) creates an `AuditRecorder`. The main server (`mcp_server.py`) uses the same redaction but does not write this file. If `audit.log` is missing, this is the likely reason.

## Add-in runtime log

The Revit add-in starts Serilog in [App.cs](../packages/revit-bridge-addin/src/Bridge/App.cs).

- The log file is `%APPDATA%\AECModelBridge\Logs\bridge.jsonl`.
- The log rolls over daily.
- It records add-in startup, shutdown, incoming requests and execution errors.

The panel hub writes its own log, `panel-hub.log`, in the same folder.

This log shows what Revit received and ran.

## Why there are two logs

The Python server and the Revit add-in run as separate processes. They do not share a runtime.

- The Python audit log tells you what the MCP server believed it asked for.
- The add-in log tells you what Revit actually received and ran.

When you investigate a problem, read both.

## What to expect when something fails

If the server sends a request and Revit fails to run it:

- The Python audit log may still look normal.
- The add-in log usually holds the useful error.

If the server rejects a path, or the payload has the wrong shape, the request never reaches the add-in:

- Look at the Python audit log and the error the client showed.
- The add-in log will have nothing for this request.

## Rule of thumb

Do not rely on one log alone. For a failed live request, compare these three records:

1. the Python audit entry
2. the add-in log entry
3. the error the client showed

This check quickly shows whether the problem is the input, the connection or Revit itself.
