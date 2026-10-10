# Frequently asked questions

Short answers for BIM coordinators. Each answer comes from the code or the docs on `main`. Where it cannot be checked from code, it is tagged **UNVERIFIED**.

New here? Start with [getting started](getting-started.md). If something fails, see [troubleshooting](troubleshooting.md).

## Privacy and control

### Does my model leave my computer?

The AEC Model Bridge server and the Revit add-in run on your machine. The add-in listens on the loopback address (`127.0.0.1`) only, and the server talks to your AI client over a local pipe. See [security](security.md).

But the answers to your questions do go somewhere. When the assistant reads your model, the tool results (element names, parameter values, counts) become part of the chat. Your AI client sends that chat to its AI provider. So what leaves your computer depends on the client you chose and its settings. Check that client's privacy terms.

Two more cases:

- The panel's built-in Claude chat uses an Anthropic API key if you set one, or the `claude` command-line tool. It sends the chat to Anthropic.
- Speckle and Autodesk cloud tools call external services, but only if you set them up with your own credentials.

### What can the AI see?

Only what the tools return. Read-only tools return things like levels, categories, parameters and QA findings for the model that is open. The server redacts secrets (tokens, keys, passwords) and turns file paths into `<redacted-path>` in logs and tool results. See [security](security.md#5-audit-logging-and-sensitive-data-redaction).

File tools can only reach the folders you list in `MCP_REVIT_ALLOWED_DIRECTORIES`. The default is one workspace folder.

One tool, `revit_execute_python`, can run raw Python on the host. It is off unless you set `MCP_REVIT_ALLOW_PYTHON_HOST=true`. Leave it off. See the [configuration reference](configuration-reference.md).

### Can the AI change my model without me clicking approve?

**The approval gate is on by default, and a tool that changes the model needs an approved plan. But today an AI client can still approve its own plan.** Here is what is true on `main` today.

- Tools that change the model are blocked unless they carry the `plan_id` of an approved plan. `MCP_REVIT_APPROVAL_MODE` is `required` by default. If you set it to anything else, the check is off. Leave it alone.
- The Revit panel's native chat cannot call `approve_plan`, `reject_plan` or `rollback_plan`. They are withheld from it.
- An external AI client, such as Claude Desktop connected over MCP, does see `approve_plan` in the tool list and can call it. The code does not check who is calling. The `approver` name is self-reported and not authenticated.
- The panel hub accepts the same call over local HTTP.

So the gate stops accidental changes and stops direct writes. It does not stop a client that decides to approve its own plan. A fix is open: [pull request #99](https://github.com/Sam-AEC/aec-model-bridge/pull/99), which binds approval to the approved action and keeps approval human-only. It is not merged at the time of writing.

What to do until then: watch what your assistant calls. Do not give it standing permission to run every tool. Many clients ask you before each tool call. Use that prompt, and decline `approve_plan` calls from the assistant.

### Can I turn the approval gate off?

Yes, with `MCP_REVIT_APPROVAL_MODE`. Don't. Any value other than `required` removes the check.

## What it works with

### Which Revit versions work?

Revit 2024, 2025, 2026 and 2027. See [install](install.md#requirements) for the build requirements by year. You can run more than one open Revit by adding one client entry for each year with `MCP_REVIT_HOST_VERSION`. Routing between several open Revit sessions is still a proposal, see [ADR 0014](0014-multi-revit-routing.md).

### Does it work on a Mac?

Revit runs only on Windows, and the add-in and installer are for Windows. So live Revit work does not work on a Mac. The registry check for a running Revit also uses a Windows call. UNVERIFIED on macOS: demo mode (`MCP_REVIT_MODE=mock`) is plain Python and should run anywhere Python 3.11 or later runs. It was run on Linux while writing this page.

### Which AI assistants work?

Setup is documented for Claude Desktop, VS Code with GitHub Copilot, Cursor and Codex. Others that can start a local MCP server should work but are untested. See [compatibility](compatibility.md).

### Does it work offline?

Part of it. The server and the Revit add-in need no internet once installed. Demo mode needs none either. But most AI assistants call a cloud AI service, so they need internet. The `uvx` install also downloads the code from GitHub the first time. UNVERIFIED: a fully local AI client with a local model was not tested.

### What is demo mode?

Demo mode (`MCP_REVIT_MODE=mock`) runs the server without Revit. Read tools answer from a small built-in sample model, and write tools return a canned `mock-response`. It changes no model. It is the default if you set no mode. It is for trying the tools, learning the approve flow, and testing.

Do not use demo mode for real work. The sample data is not your model. In live mode the tools that need a snapshot refuse to fall back to sample data.

## Cost and licence

### How much does it cost?

The software is free to use under the GPL option. You pay for your AI assistant yourself, if it charges. Revit needs its own licence. A separate commercial licence is available for proprietary use. See [LICENSING](../LICENSING.md).

### What is the licence?

Your choice of GPL-3.0-or-later with the Revit Linking Exception, or a commercial licence agreed in writing. Versions 1.0.2 and earlier were MIT. The [licensing page](../LICENSING.md) explains it. It is not legal advice.

## Using it

### What can I ask it to do first?

Start with read-only work: summarize the model, run the core QA check, list issues. These change nothing. Then try one small change through a plan. The [getting started](getting-started.md) tutorial shows this in demo mode.

### Has it been tested in a real Revit?

Read-only tools are checked in code. **Model writes have not been run in a real Revit.** A crash bug on model writes has a fix in [pull request #95](https://github.com/Sam-AEC/aec-model-bridge/pull/95), which is open at the time of writing. Do not try writes on a project model. Use a throwaway copy, and only after the fix is merged and the add-in is rebuilt. See [part 4 of getting started](getting-started.md#part-4-live-revit-unverified) and the [demo runbook](demo-runbook.md).

### How do I undo a change?

There are three ways. All of them are UNVERIFIED in live Revit.

1. **Revit Undo.** Press Ctrl+Z straight after the run, in the same Revit session. Each parameter write is its own named transaction, so you may need to press it once per change.
2. **`rollback_plan`.** Writes the recorded before values back. It skips an action that has no recorded before value, and says so in `rollback_warnings`. The plan state may still read `rolled_back`, so read the warnings and check with a new snapshot.
3. **`plan_revert`.** Drafts a new plan that restores the before values. You still approve and run it. It refuses when a before value was empty.

If a parameter was empty before the change, options 2 and 3 cannot restore it. Use Ctrl+Z. See [proof and revert](proof-and-revert.md).

### How do I know what was changed?

Ask for the proof bundle (`get_proof_bundle`) of the plan. It lists the elements, the before and new values, who approved and when. It records what the server asked for. To confirm the model, take a new snapshot and run the check again. See [proof and revert](proof-and-revert.md).

### What does "UNVERIFIED" mean in these docs?

It means the claim could not be confirmed from the code, or it needs a live Revit session that nobody has run yet. Treat it as a test to do yourself, not as a promise.

### Where are my plans and files stored?

In the workspace folder, `~/Documents/AEC Model Bridge` by default. Plans go in `plans`, proofs in `proofs`, snapshots in `snapshots`. The QA issue store `qaqc_issues.db` is there too. Set another folder with `MCP_REVIT_WORKSPACE_DIR`.

## Maintenance

### How do I uninstall it?

If you used the installer: close Revit, then open **Apps > Installed apps > AEC Model Bridge > Uninstall**. See [install](install.md#download-the-installer). Both Setup and the uninstaller stop if Revit is running.

Remove the `aec-model-bridge` entry from your AI client's MCP settings. If you ticked *Set up Claude Desktop and VS Code* in the installer, it saved a `.aec-backup-<date>` copy of your old settings first. UNVERIFIED: whether the uninstaller restores that copy. Check your settings file yourself.

The workspace folder is not part of the program. Delete it yourself if you no longer need your plans, proofs and reports.

For a source install: delete the add-in files under `C:\ProgramData\AECModelBridge` and the manifest at `%APPDATA%\Autodesk\Revit\Addins\<year>\AECModelBridge.addin`, then delete the repository folder and its `.venv`.

### How do I update it?

Run the newer installer. Running it again upgrades the existing install. See [install](install.md#download-the-installer) and [versioning](versioning.md).

### Where do I report a bug or ask a question?

Open an issue on [GitHub](https://github.com/Sam-AEC/aec-model-bridge/issues). [Troubleshooting](troubleshooting.md#what-to-copy-into-a-bug-report) lists what to include.
