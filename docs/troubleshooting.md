# Troubleshooting

Find your symptom, check the likely cause, and try the fix. Every entry says where to look and what to copy into a bug report.

Each entry comes from a failure mode in the code. Claims about Windows, antivirus or a particular AI client that the code cannot show are tagged **UNVERIFIED**.

## Where the logs are

| Log | Location | What it shows |
| --- | --- | --- |
| Add-in log | `%APPDATA%\AECModelBridge\Logs\bridge.jsonl` | What Revit received and ran. Rolls over daily. |
| Panel hub log | `%APPDATA%\AECModelBridge\Logs\panel-hub.log` | The hub the Revit panel talks to. Rotates at about 1 MB and keeps 3 old files. |
| Bridge registry | `%LOCALAPPDATA%\AECModelBridge\registry\revit-<pid>.json` | The address and session token the add-in publishes when Revit starts. |
| Plans and proofs | `<workspace>\plans\` and `<workspace>\proofs\` | One JSON file per plan and per finished plan. |
| Audit log | `audit.log` in the server's working directory | Only written by the legacy server. The main server does not write it. See [logging and audit](logging-and-audit.md). |
| MCP client log | Depends on your client | Where the client shows why it could not start the server. UNVERIFIED: the location differs by client, so look in its settings or help menu. |
| Installer log | The path you give to `/LOG=` | Only when you ran the installer with that switch. See [install](install.md#download-the-installer). |

The workspace is `~/Documents/AEC Model Bridge` unless you set `MCP_REVIT_WORKSPACE_DIR`.

**Quick check of the whole setup:** while the panel hub runs, open `http://127.0.0.1:8787/diagnostics` in a browser. It returns a list of checks (`hub`, `mode`, `revit_bridge`, `workspace`, `ai_provider`). Each failing check carries a `next_step`. Use the port you set in `MCP_PANEL_HTTP_PORT` if you changed it.

## What to copy into a bug report

Open an issue on [GitHub](https://github.com/Sam-AEC/aec-model-bridge/issues) and include:

- The exact error text, copied, not retyped.
- Your Revit year and the AEC Model Bridge version (the installer file name or `VERSION`).
- How you installed: installer, release package, source, or `uvx`.
- The mode: `mock` or `bridge`.
- The last 50 lines of `bridge.jsonl` and `panel-hub.log`.
- The output of `/diagnostics`, if the hub is running.
- The plan file from `plans\` if the problem is about a plan. Remove project names first.

Do not paste the session token from a registry file, or any API key. The token is in the `session_token` field.

---

## Connection problems

### The bridge is not found, or there is no registry file

**You see:** an error such as `No live Revit 2026 bridge found. Available Revit versions: none.` Or the server runs and every Revit tool fails. Or the folder `%LOCALAPPDATA%\AECModelBridge\registry` is empty or missing.

**Cause:** the add-in writes a registry file when Revit starts. The server reads that file to find the bridge. No file means the add-in did not start, or Revit is not running. The server also deletes registry entries whose process is gone or that are older than 7 days.

If you set `MCP_REVIT_HOST_VERSION`, the server only accepts a bridge for that year. With no registry entry and no year set, it falls back to port 3000 and logs that tokenless connections are deprecated.

**Fix:**

1. Start Revit and open a project.
2. Check for the **AEC Bridge** tab on the ribbon. If it is missing, the add-in did not load. Check that the add-in was installed for your Revit year (see [install](install.md)).
3. Look for a `revit-<pid>.json` file in the registry folder.
4. If `MCP_REVIT_HOST_VERSION` is set, make sure it matches the running Revit year, or remove it.
5. Restart your AI client so the server reads the registry again.

**Look at:** the registry folder, `bridge.jsonl` (it logs `Wrote registry file`), and the add-in install folder `C:\ProgramData\AECModelBridge\bin\<year>`.

### The token does not match (401 Unauthorized)

**You see:** an error that mentions `401` or `Unauthorized` when a tool calls Revit.

**Cause:** the add-in creates a new random token each time Revit starts and writes it to the registry file. The server reads the token once, when it starts, and keeps it. If you restart Revit while your AI client stays open, the server holds the old token. The add-in rejects every request except `/health` when the token is wrong.

**Fix:** restart your AI client, or start a new chat that starts a new server, so the server reads the new registry file. Do not copy tokens by hand.

**Look at:** `bridge.jsonl`, and the time in the `started_at` field of the registry file compared with when you started Revit. **Copy to the bug report:** the error text and `started_at`. Not the token.

### Revit is not running

**You see:** `Bridge unreachable at http://127.0.0.1:... Ensure Revit is running with the AEC Model Bridge add-in loaded.` The server retries three times before it gives up, so the error can take a few seconds to appear. The client may also show `Make sure: 1. Revit is running ...`.

**Cause:** the server cannot reach the add-in. Revit is closed, still starting, or the add-in is not loaded.

**Fix:** start Revit, open a project, wait for the **AEC Bridge** tab, and try again. If Revit is open, run the health check in [install](install.md#verify-the-bridge). Check that the add-in year matches the running Revit year.

### The panel hub cannot start, port 8787 is in use

**You see:** the Revit panel shows a connection error. `panel-hub.log` is empty or missing. The `bridge.jsonl` file may hold `Launched the panel hub but it never became reachable on 127.0.0.1:8787`.

**Cause:** the add-in starts a small background hub for the panel on port 8787. If something already answers `/health` on that port, the add-in leaves it alone and uses it. If another program holds the port and does not answer like the hub, the new hub cannot start. A second reason is that no Python could be found. `bridge.jsonl` then says `no Python interpreter could be found`.

**Fix:**

- Port in use: find the program using port 8787 and close it. Or set the environment variable `MCP_PANEL_HTTP_PORT` to a free port (for example `8788`) for both Revit and the hub, then restart Revit.
- No Python: install Python 3.11 or later, or set `AEC_MODEL_BRIDGE_PYTHON` to the full path of a `python.exe`. The installer ships a Python at `C:\ProgramData\AECModelBridge\python\python.exe`, which the add-in tries first.
- To start the hub by hand: `aec-model-bridge-panel-server` or `python -m revit_mcp_server.panel_server`.

**Look at:** `bridge.jsonl` and `panel-hub.log`.

### "No active document"

**You see:** a tool fails with `No active document`.

**Cause:** the add-in handles requests for the active Revit document. None is open. This happens at the Revit start screen, or when only a family or a non-project window is active. Tool errors come from the add-in (`BridgeCommandFactory.cs`).

**Fix:** open a project in Revit and make its window the active one. Try the tool again.

**Look at:** `bridge.jsonl` for the failing request.

---

## Approval problems

### Live mode rejects an empty snapshot_id

**You see:** `... requires a snapshot_id when connected to Revit (mode='bridge'). Capture one first with the snapshot tool and pass its snapshot_id; generated mock data is only used when MCP_REVIT_MODE=mock.`

**Cause:** the QA check, parameter manager, report generator and clash triage will not fall back to sample data in live mode. This is on purpose. Sample data must never pass for your model.

**Fix:** ask the assistant to take a snapshot (`revit_extract_snapshot`) and pass the `snapshot_id` it returns to the next tool. If you meant to try the tools without Revit, set `MCP_REVIT_MODE=mock`.

**Look at:** the tool result text. Some other modules, for example `model_inspector`, may behave differently in live mode. UNVERIFIED: check the tool's own error message.

### The approval gate blocks a tool because there is no plan_id

**You see:** `Approval Gate Blocked: Approval mode is enabled. Mutating tool '<name>' requires a valid 'plan_id' parameter.`

**Cause:** a tool that changes the model was called without a plan. The gate is on by default.

**Fix:** this is the gate doing its job. Ask the assistant to make a plan with `plan_actions`, approve it, then run `execute_plan`. Do not set `MCP_REVIT_APPROVAL_MODE` to anything other than `required` to get around it. Any other value turns the check off.

### The plan is not approved

**You see:** `Plan '<id>' is in state 'pending', not 'approved'. Execution blocked.` The state may also be `rejected`, `executed`, `partial` or `rolled_back`. You may also see `Plan '<id>' does not exist.`

**Cause:** the plan is waiting for approval, was rejected, or already ran. A plan id that does not exist usually has a typo, or the server is using a different workspace folder than the one that holds the plan file.

**Fix:** list pending plans. Approve the right one in the panel (Plans tab, then Approve). For a rejected or finished plan, make a new plan. If the plan file is missing, check that your client and the hub use the same `MCP_REVIT_WORKSPACE_DIR`.

**Look at:** `<workspace>\plans\<plan_id>.json` and its `state` field. **Copy to the bug report:** that file, with project names removed.

### Approve does nothing in the panel

**Cause:** the hub may have refused the call. The panel Run Log shows a `Plan approve` entry as soon as you click, even if the hub says no.

**Fix:** press Refresh and check the plan state. An `Error: plan.approve` entry in the Run Log means the hub rejected the call. Check `panel-hub.log`. See the [demo runbook](demo-runbook.md) for more.

---

## Workspace and files

### The workspace is not writable

**You see:** in `/diagnostics`, the `workspace` check fails with `Workspace is not writable`. Or a tool says a path `is outside the allowed workspace directories`.

**Cause:** two different things use the same word. The first is a folder that Windows will not let you write to. The second is a path outside the folders listed in `MCP_REVIT_ALLOWED_DIRECTORIES`.

**Fix:** set `MCP_REVIT_WORKSPACE_DIR` to a folder you can write to, using an absolute path. List every folder you need in `MCP_REVIT_ALLOWED_DIRECTORIES`, separated by semicolons. Restart the hub and your client. See the [configuration reference](configuration-reference.md).

**Look at:** `http://127.0.0.1:8787/diagnostics`.

### Add-in and server use different workspaces

**You see:** a snapshot id is returned but the server says `Snapshot '<id>' not found.`

**Cause:** the add-in and the Python server each have a workspace setting. If they differ, the snapshot is saved where the server does not look. The [demo runbook](demo-runbook.md) lists this as a likely first failure. There is an open change to align them (#71).

**Fix:** point both at the same folder, and restart Revit and the client.

---

## Install problems

### Windows or antivirus blocks the installer

**You see:** Windows SmartScreen says the publisher is unknown. Or your antivirus quarantines or blocks `AECModelBridge-Setup-<version>.exe`.

**Cause:** the installer is not code-signed yet. This is stated in the [install guide](install.md#download-the-installer). That is why SmartScreen warns. UNVERIFIED: whether a given antivirus product will flag it. That depends on the product.

**Fix:**

1. Download only from the [latest release](https://github.com/Sam-AEC/aec-model-bridge/releases/latest).
2. Compare the file with the checksum in `SHA256SUMS.txt` on the same page. In PowerShell: `Get-FileHash .\AECModelBridge-Setup-<version>.exe -Algorithm SHA256`.
3. If the hashes match, choose **More info**, then **Run anyway**.
4. If your antivirus blocks it, ask your IT team to allow it, or use the [source install](install.md#install-from-source).

If the hashes do not match, do not run the file. Report it.

**Copy to the bug report:** the antivirus product name, the exact warning text, and the hash you computed.

### Python or uv is missing for the uvx install

**You see:** the client says `uvx` is not found or is not recognized. Or Python is older than 3.11.

**Cause:** the one-click install buttons and the README entry run `uvx`, which comes with [uv](https://docs.astral.sh/uv/getting-started/installation/). The package needs Python 3.11 or later. `uvx` also fetches the code from GitHub, so it needs Git.

**Fix:** install uv, close and reopen your client so it sees the new PATH, then retry. Check in a terminal: `uvx --version` and `git --version`. Or use the source install in [install](install.md#install-from-source), which uses a virtual environment.

### The MCP client cannot start the server

**You see:** the client shows the server as failed, stopped, or not connected. No tools appear.

**Cause (check in this order):**

1. The JSON config has a typo, such as a missing comma or a single backslash in a Windows path. Paths need `\\`.
2. The `command` is not found (see the entry above).
3. The server crashed at start. A bad value in an `MCP_REVIT_*` variable (for example a folder that does not exist in `MCP_REVIT_ALLOWED_DIRECTORIES`) is a likely cause. UNVERIFIED: not every bad value was tested.
4. The first `uvx` run is still downloading and the client timed out. UNVERIFIED: timeouts differ by client.

**Fix:** run the same command in a terminal and read the error. For a source install:

```powershell
.\.venv\Scripts\python.exe -m revit_mcp_server.mcp_server
```

A healthy server starts and waits silently for input. Press Ctrl+C to stop it. Then fix what the terminal showed, and restart the client.

**Copy to the bug report:** your config with any keys removed, and the terminal error.

### The add-in does not appear in Revit

**Cause:** the installed year does not match the Revit year, the manifest is missing, or Revit was open while you installed.

**Fix:** close Revit and run the installer again. Tick your Revit year. Look for `%APPDATA%\Autodesk\Revit\Addins\<year>\AECModelBridge.addin`. See [install](install.md#troubleshooting).
