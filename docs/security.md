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

### Panel HTTP shim (`panel_server.py`)
The panel hub (`aec-model-bridge-panel-server`, default port 8787) listens on `127.0.0.1` and serves `/execute`, `/agent/chat`, `/diagnostics`, `/reports`, `/agent/providers` and `/health`. Its only intended caller is the add-in's C# `HubClient`. Every request is checked:

- `Host` must be `127.0.0.1:<port>` or `localhost:<port>` (the port the hub is actually bound to), otherwise 403.
- Any request carrying an `Origin` header, including `Origin: null`, is refused with 403. `HubClient` sends no `Origin`.
- `POST` requires `Content-Type: application/json` (a `charset` parameter is accepted), otherwise 415.
- `OPTIONS` is not handled and no CORS headers are sent.
- `GET /health` returns only `{"status": "healthy"}` and needs no token. Every other route, including `/execute`, `/agent/chat`, `/diagnostics`, `/reports`, `/agent/providers` and unknown paths, needs the per-install token (next section).

#### Panel hub token

The hub requires the header `X-AMB-Token` on every route except `GET /health`. A missing or wrong token gets `401` with the body `{"ok": false, "error": "Unauthorized"}`; the two cases are indistinguishable. The check is `hmac.compare_digest` and runs after the Host, Origin and Content-Type checks. Failed attempts are counted per hub process (20 per minute); past that, a failing request gets `429` without further work. A request with the right token is never counted or limited, so noise on the port cannot lock the panel out.

- **One secret per Windows user.** 32 random bytes (`secrets.token_urlsafe(32)`, 43 characters) in `%LOCALAPPDATA%\AECModelBridge\panel-hub.token`, beside the add-in's `registry` folder. `MCP_PANEL_TOKEN_FILE` overrides the path.
- **The first hub to start creates it; everyone else reads it.** The file is written to a temp name with owner-only access and hard-linked into place, which fails if the name already exists, so two hubs starting together end up with one file and one token. Every later hub and every Revit's `HubClient` reads the same file, so all Revits sharing the hub use one token. The add-in never creates the file.
- **Owner-only.** On Windows the file's inheritance is removed and only the current user is granted access (`icacls`); if that fails, the hub does not start. On POSIX the mode is `0600`, and a file that is a symlink, owned by someone else, or accessible to group or others (any `0o077` bit) is refused with an error that names the file but never the token. Windows does not re-verify the ACL on read.
- **Never written elsewhere.** The token is not logged, not in audit logs, plans, proof bundles, diagnostics, chat or error messages. `redact_data` masks it by value and by the header name, and the hub's log file filter masks it as a second line of defence.
- **The page never sees it.** The panel's JavaScript does not call the hub. It posts messages to C# (`window.chrome.webview.postMessage`), and only `HubClient` calls the hub; a test checks that `panel/` contains no network calls and no reference to the token.
- **Rotation.** Stop every hub (end the `revit_mcp_server.panel_server` Python process), delete `panel-hub.token`, then start Revit. The next hub writes a new token. A running hub keeps the token it started with: if the file changes underneath it, the hub logs "token file changed ... restart the hub", and the panel, after one re-read of the file and one retry, shows "token changed" with the same instruction. An older hub (before this change) ignores the header; an older add-in talking to a new hub gets `401`. Update both together.

**What the token is, and is not.** It proves "a process running as this Windows user", and it keeps out browser pages (already blocked by the Host/Origin checks), other Windows users and sandboxed software without access to your profile. It does not prove a person is present. Anything running as the same user, including an AI agent with a shell on your account, can read the file and call the hub. The real boundary is OS user separation plus the human-only approval flow: approving a plan from the panel is still recorded as `approved_via: "panel"` and the AI paths cannot reach `approve_plan`, `reject_plan` or `rollback_plan`. Do not give an AI client a shell on the account you approve plans with. Other limits: the token travels over plain loopback HTTP, and any process that can read your user's files can read it.

#### Several Revits (instance routing)

One hub serves every open Revit. Requests that act on Revit carry an `instance` field, `{"pid": <Revit process id>, "document": <active document title>}`, which `HubClient` fills in from its own process. The hub looks the pid up in the live bridge registry (`%LOCALAPPDATA%\AECModelBridge\registry`, see [ADR 0014](0014-multi-revit-routing.md)) and sends that request to that Revit's bridge; the endpoint and bridge token always come from the registry, never from the request. Without `instance`: a single live Revit is used; more than one is refused with `409` and a list of the live instances (pid, Revit year, start time). A pid with no live bridge is refused the same way. Plan-only tools (`plan_actions`, `list_pending_plans`, `approve_plan`, `reject_plan`, `get_proof_bundle`) never reach Revit and need no `instance`. Chat through the `claude` or `codex` command-line tool is refused while several Revits are open, because the CLI starts its own MCP server that cannot be pinned yet; the built-in assistant (API key) is routed. The document title is shown for people only: the registry does not hold it, so it is not matched. A recycled pid is the open item in ADR 0014, and plans do not yet record which Revit created them. UNVERIFIED against a live Revit.

What this does not do: it does not stop software running as the same user, and it does not change tool approval semantics; mutating tools remain gated by the approval flow.

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
- **Approval modes.** `MCP_REVIT_APPROVAL_MODE` takes one of three modes (the value is trimmed and case-insensitive):
  - `look_only`: every tool that changes the model is refused with "Look only mode: this tool changes the model. Switch to Ask me first in the panel or settings." Tools that only read keep working. The refusal applies on every path a model can reach (MCP calls, the panel's chat assistant, recipe steps and other module tool executors, `execute_plan`, and the panel's `/execute` route), and `rollback_plan` is refused too. A plan can still be drafted, but nothing in it can run until the mode is changed.
  - `ask_first` (the default; `required` is the older name and means the same): a mutating tool needs an approved, unchanged plan action, as described above.
  - `auto`: the approval check is off (see "Not protected"). This is the only way to turn it off, and it must be named explicitly.
- **`approval_mode` fails closed.** Any value that is not one of `look_only`, `ask_first`, `required` or `auto` (a typo, an empty string, `off`, `false`) behaves as `ask_first` and logs a warning. Earlier wording of this rule said `required`; it is the same behaviour under the new name.
- **The mode cannot be changed over MCP.** No MCP tool sets it; it comes from the environment variable (or the server configuration) when the hub starts. The hub reports the current mode, normalised to `look_only`, `ask_first` or `auto`, as `approval_mode` in the approval provider's health result, so the panel can show it later. UNVERIFIED: how the Revit panel shows or switches the mode, and the behaviour against a live Revit session; the hub tests use mock providers only.

### Not protected

- **`MCP_REVIT_APPROVAL_MODE=auto`** turns the gate off entirely. Use `look_only` instead when you want the opposite: no model changes at all.
- **The panel's `/execute` endpoint authenticates a local process, not a person.** It needs the per-user token (see the panel hub token section above) and passes the Host, Origin and Content-Type checks, which keeps out browser pages and other Windows users. Any process running as you can read the token file and approve a plan through it (recorded as `panel`). The panel's Plans view also shows only tool names, not full arguments; review arguments with `aec-model-bridge-approve show` when it matters.
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
- [ ] Keep `MCP_REVIT_APPROVAL_MODE` at `ask_first` (or `required`), so every model change needs an approved plan. Use `look_only` to block model changes entirely.
