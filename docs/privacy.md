# Privacy

> **DRAFT for owner sign-off.** The project owner must read and approve this page before it is published or linked from a marketplace listing. Last code check: 2026-10-10, against version 1.4.0.

AEC Model Bridge is software that runs on your own computer. This page says what it does with your data, in plain words. It is about the software in this repository. It is not about the AI service you connect to it, which has its own privacy terms.

## Short version

- The project runs no servers and collects no data about you. It has no telemetry, no analytics and no crash reporting.
- Your Revit model is read by software on your computer. Whatever the assistant reads from your model is sent to the AI provider you connected, because that is how the assistant can answer. That provider's privacy policy applies to it.
- Logs, plans and proof files stay in folders on your computer. You can delete them.

## What runs on your computer

- The MCP server (a Python program) that your AI client starts.
- The Revit add-in and its side panel.
- A local connection between the two, on your own machine (`127.0.0.1`). It does not accept connections from other computers.
- Optional: the VS Code extension. It only checks that the local bridge is running.

## What leaves your computer

| What | Where it goes | When |
|---|---|---|
| Tool results the assistant reads from your model (element names, parameter values, counts and so on), and what you type in chat | The AI provider behind the client you use (for example Anthropic, OpenAI, Google, Microsoft or a local model) | Whenever you use the assistant. The project does not control or see this. Check your provider's privacy policy and your plan's data settings. |
| Chat messages and tool results from the Revit panel's built-in chat | Anthropic's API, if you set `MCP_REVIT_ANTHROPIC_API_KEY`. If you did not, the panel uses the `claude` command-line tool if it is installed, and that tool talks to Anthropic. | Only when you use the built-in chat |
| Requests to Speckle (default `https://app.speckle.systems`, or your own server) | Speckle | Only if you use the Speckle tools and sign in |
| Requests to Autodesk Platform Services (`developer.api.autodesk.com`) | Autodesk | Only if you use the cloud tools with your own Autodesk credentials |
| Downloads of the software itself (for example `uvx` fetching the server from GitHub, or `pip` fetching packages from PyPI) | GitHub, PyPI | When you install or update. Those services see the download request as for any download. |

If you use only mock mode (sample data, no Revit), the model data is fake sample data. The assistant still sends what it reads to your AI provider.

## What the project does not do

We searched the code in this repository (the Python server, the Revit and Rhino add-ins, the VS Code extension and the install scripts) for analytics, telemetry, crash reporting, update checks and calls to a project-run server. We found none. The only network code is the list above: the local bridge, the optional Anthropic chat, Speckle, Autodesk Platform Services and the extension's local health check. This is a code review at the date above, not a guarantee about future versions. If that ever changes, it will be opt-in and written here first.

The software does not read your files outside the workspace folders you allow. See [security.md](security.md).

## Where your files and logs live (Windows)

| What | Where |
|---|---|
| Workspace: approval plans (`plans`), proof bundles (`proofs`), model snapshots (`snapshots`) and files the tools write | `Documents\AEC Model Bridge` by default, or the folder in `MCP_REVIT_WORKSPACE_DIR` |
| Audit log of tool calls (if enabled) | The file in `MCP_REVIT_AUDIT_LOG`. Secrets, tokens and file paths are redacted before writing. See [logging-and-audit.md](logging-and-audit.md). |
| Add-in log and panel log | `%APPDATA%\AECModelBridge\Logs` (`bridge.jsonl`, `panel-hub.log`) |
| Bridge endpoint files (which port Revit uses) | `%LOCALAPPDATA%\AECModelBridge\registry` |
| Installed program files | `C:\ProgramData\AECModelBridge` |
| Backups of your AI client settings made by the installer | Next to the original file, named `.aec-backup-<date>` |

Plans and proof bundles can contain element names and parameter values from your project. Treat the workspace folder as project data.

## How to delete everything

1. Close Revit and your AI client.
2. Uninstall: Windows *Apps > Installed apps > AEC Model Bridge > Uninstall*.
3. Delete these folders if they still exist: `Documents\AEC Model Bridge` (or your own workspace folder), `%APPDATA%\AECModelBridge`, `%LOCALAPPDATA%\AECModelBridge`, `C:\ProgramData\AECModelBridge`.
4. Delete the audit log file you set in `MCP_REVIT_AUDIT_LOG`, if any.
5. Remove the `aec-model-bridge` entry from your AI client's MCP settings, and delete any `.aec-backup-*` files you do not need.

Data held by your AI provider, Speckle or Autodesk is deleted through those services, not from this computer.

## Questions

Open an issue at <https://github.com/Sam-AEC/aec-model-bridge/issues>. For security problems, see [SECURITY.md](../SECURITY.md).
