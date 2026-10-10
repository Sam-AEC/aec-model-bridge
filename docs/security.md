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
- `GET /health` returns only `{"status": "healthy"}`.

What this does not do: there is no authentication token yet, so it does not stop other software running as the same user from calling the port directly with a valid `Host` and no `Origin`. It does not change tool approval semantics; mutating tools remain gated by the approval flow. A token is planned separately.

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
- **An approval covers exactly what was shown.** When a plan is drafted, the server stores a content hash (`plan_hash`) of its id, creation time, snapshot id, skipped list, actions (tools, arguments, before values) and, when the plan carries one, its `review` block (summary, reasoning, citations, assumptions, elements left out, warnings) and `reverts_plan_id`. Plans with a review carry `hash_version: 2`; plans without one are hashed with the original rule and still verify. A plan that mixes the two (a review without version 2, or version 2 without a review) cannot be approved or executed. The review block is strictly validated (unknown keys, wrong types and over-long text are refused; total size is capped at 64 KB), stored as given and escaped when shown by `aec-model-bridge-approve show`. Anything else on a plan file is metadata that is **not hashed and not shown as approved content**: any extra key passed to `create_plan(extra=...)` (for example `reasoning` or a note), plus the lifecycle fields (`state`, `plan_hash`, `approved_*`, `rejected_*`, `executed_at`, `results`, `is_reversible`, `reversible_strategy`). `show` lists such keys under "Not part of the approval". `plan_revert` puts its conflicts, notes and warnings into the review block, so they are hashed and shown. The panel does not yet render the review block (follow-up); use `show` until it does. The command-line tool prints the plan and its hash, and the panel sends back the `plan_hash` of the list it rendered. The approval is refused if the plan on disk no longer has that hash when the person confirms, or if it no longer matches the hash stored when it was drafted. On approval the hash is stored as `approved_hash`.
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

### Which tools the gate covers (fail closed)

- **Proxied tools.** Tools forwarded to an external MCP server (`providers/proxy.py`) are unknown to this server, so each one is treated as a model change and needs an approved plan. It skips the gate only if its upstream name starts with `get_`, `list_`, `read_`, `query_`, `search_` or `describe_` and the upstream advertises `readOnlyHint: true`. If the upstream sends no `readOnlyHint` at all, the name prefix alone decides. `readOnlyHint: false` or `destructiveHint: true` always means gated. Users of proxied servers therefore need plan approval for any proxied write.
- **Navisworks.** Only `health`, `get_document_info`, `get_model_tree`, `get_selection`, `list_viewpoints`, `list_clash_tests` and `get_clash_results` skip the gate. Every other Navisworks tool, including any added later, is gated. This includes `navisworks_reflect_get` and `revit_reflect_get`: a property getter on an arbitrary object can have side effects.
- **UNVERIFIED:** `revit_calculate_material_quantities` stays ungated although the Revit add-in marks it mutating. The flag looks wrong, but this needs a Revit run to confirm; it is listed in `KNOWN_UNGATED` in `tests/test_addin_hub_contract.py`.

### Not protected

- **`MCP_REVIT_APPROVAL_MODE=auto`** turns the gate off entirely. Use `look_only` instead when you want the opposite: no model changes at all.
- **The panel's `/execute` endpoint is not authenticated.** Any local process that can send HTTP requests to the panel hub can approve a plan through it (it is recorded as `panel`). PR #93 adds Host, Origin and Content-Type checks that stop browser pages from reaching it; a per-session token for the panel is still being designed. Until both land, treat the panel hub port as trusted-local only. The panel's Plans view shows, for each pending plan, the escaped tool and arguments (since PR #99), and a before-value only when one was captured. `plan_actions` captures a before-value only for `revit_set_parameter_value`; for every other action (deletes, batch updates and so on) the before-state is recorded empty and the panel shows no before row, so a missing row does not mean nothing changes. `aec-model-bridge-approve show` remains the independent cross-check. The Plans view lists pending plans only (`ApprovalGate.list_pending_plans`); `aec-model-bridge-approve show <plan_id>` works for a plan in any state, while `proofs/` bundles exist only for plans that were executed (or attempted); approved-but-unexecuted and rejected plans have none.
- **The command-line tool does not authenticate who is typing.** Software that can run shell commands as you can run `aec-model-bridge-approve approve <id> --yes`. Do not give an AI client a shell on the same account if you rely on the gate.
- **Names are not identities.** `approved_by` is the local account name, not a verified person.
- **Write access to the workspace defeats the hash check.** The hashes detect a plan that was changed after drafting or approval. Software that can write the plans folder can still replace a plan's actions and its stored hashes together, or delete claim files. Keep AI clients' file-write tools out of the workspace folder.
- Plans drafted before this change have no `plan_hash` and cannot be approved; draft them again.

### Before any release

- **The panel approves review-bearing plans without showing the review (M1).** The panel sends back the stored `plan_hash`, which covers `review`, but renders only the actions. A revert plan with conflict warnings can therefore be approved from the panel without the person seeing them. The panel route must either refuse plans with `hash_version` 2 and non-empty review content (and point to `aec-model-bridge-approve show`) or render the review escaped. This is planned as a separate change after the panel token work (PR #115) merges, because both touch `panel_server.py` and `panel/`.
- **Known limit (large plans):** each claimed action rewrites the whole plan file and re-verifies it, so executing a plan costs O(n^2) in its action count; keep plans to a few hundred actions.
- **Release note:** reject any pending revert plan drafted before upgrading. Older revert plans keep their conflicts, notes and warnings outside the hash; `show` prints them under "NOT covered by the approval".

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
