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

## 4a. Plan approval: what is and is not protected

A model that wants to change a model must draft a plan, and a person must approve it.

### Protected

- **Humans approve.** `approve_plan`, `reject_plan` and `rollback_plan` are not listed to MCP clients and are denied to the panel's Claude chat. They are also refused on every internal path a model can reach: MCP calls, the panel chat, recipe steps and other module tool executors, `execute_plan`, and the approval provider's own tool entry point. A plan cannot contain one of them as an action. Only two routes run them: the panel route (`/execute` in the panel hub, recorded as `approved_via: "panel"`) and the command-line tool `aec-model-bridge-approve list | show <plan_id> | approve <plan_id> | reject <plan_id>` (recorded as `approved_via: "cli"`).
- **The route records the channel and the account.** `approved_via` is set by the code path and `approved_by` is the operating-system account that runs the panel hub or the command-line tool. Values a caller puts in the tool arguments (`approver`, `approved_via`) are ignored.
- **Plan ids are checked.** A `plan_id` must have the exact shape `plan_` plus 12 hex characters, and must resolve to a file directly inside `<workspace>/plans`. A plan file whose `plan_id` field differs from its file name is refused. A path, `../`, or any other shape is refused with a plain error.
- **An approval covers exactly what was shown.** When a plan is drafted, the server stores a content hash (`plan_hash`) of its id, actions, tools, arguments and before values. The command-line tool prints the plan and its hash, and the panel sends back the `plan_hash` of the list it rendered. The approval is refused if the plan on disk no longer has that hash when the person confirms, or if it no longer matches the hash stored when it was drafted. On approval the hash is stored as `approved_hash`.
- **An approved plan that is edited is refused.** Before an approved action runs (direct call or `execute_plan`), the server recomputes the hash and refuses if it differs from `approved_hash`.
- **Each approved action runs at most once.** A tool call that carries a `plan_id` must match a not-yet-run action in that plan (same tool, same arguments; `plan_id`, `run_async` and `idempotency_key` are ignored). The action is consumed before the tool runs, under a per-plan lock and with a per-action claim file created exclusively (`plans/.claims/`). Concurrent calls for the same action therefore run it once, and editing an action's state back to `pending` does not reopen it. If the tool fails or the bridge times out, the action stays consumed and is marked `failed`, and the plan becomes `partial`; ask for a new plan to retry. A `run_async` call consumes its action when it is queued.
- **A person can withdraw an approval.** A plan that is `approved` but not yet fully executed can still be rejected (panel or `aec-model-bridge-approve reject`). Executed or rolled-back plans cannot be rejected.
- **The command-line tool prints model text safely.** Control and format characters in tool names, argument keys and values (terminal escape sequences, carriage returns, bidirectional overrides) are shown as visible escapes such as `\x1b`. A plan whose arguments are not an object is shown with a plain message and cannot be approved.
- **`approval_mode` fails closed.** The value is trimmed and lower-cased. Only `auto` turns the gate off. Any other value, including typos, behaves as `required` and logs a warning.

### Not protected

- **`MCP_REVIT_APPROVAL_MODE=auto`** turns the gate off entirely.
- **The panel's `/execute` endpoint is not authenticated.** Any local process that can send HTTP requests to the panel hub can approve a plan through it (it is recorded as `panel`). PR #93 adds Host, Origin and Content-Type checks that stop browser pages from reaching it; a per-session token for the panel is still being designed. Until both land, treat the panel hub port as trusted-local only. The panel's Plans view also shows only tool names, not full arguments; review arguments with `aec-model-bridge-approve show` when it matters.
- **The command-line tool does not authenticate who is typing.** Software that can run shell commands as you can run `aec-model-bridge-approve approve <id> --yes`. Do not give an AI client a shell on the same account if you rely on the gate.
- **Names are not identities.** `approved_by` is the local account name, not a verified person.
- **Write access to the workspace defeats the hash check.** The hashes detect a plan that was changed after drafting or approval. Software that can write the plans folder can still replace a plan's actions and its stored hashes together, or delete claim files. Keep AI clients' file-write tools out of the workspace folder.
- Plans drafted before this change have no `plan_hash` and cannot be approved; draft them again.

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
