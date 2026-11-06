# Frequently asked questions

Start with [getting started](getting-started.md). For connection failures, see [troubleshooting](troubleshooting.md).

## Privacy and control

### Does my model leave my computer?

The server, add-in and local bridge run on your computer. Model information returned by tools becomes part of your conversation with the AI provider. Panel chat uses the selected Claude or Codex provider, with that provider's configured service and privacy settings. Optional Speckle and Autodesk tools contact those services when configured. See the [privacy draft](privacy.md).

### What can the AI see?

The assistant sees what tools return, including element names, parameters and findings. File arguments checked by the workspace guard are limited to `MCP_REVIT_ALLOWED_DIRECTORIES`.

Host-script tools such as `revit_execute_python` and `rhino_run_python` run approved code with the host process permissions. Their script bodies are not sandboxed by the workspace guard. `MCP_REVIT_ALLOW_PYTHON_HOST` controls the module `python.host` permission; it does not disable these provider tools. Review scripts before approval. See [security](security.md).

### Can the AI change my model without me clicking approve?

The default `ask_first` mode requires an approved plan matching the reviewed tool and arguments. `required` is a compatibility alias. Approval, rejection and rollback are human-only operations through the local panel channel; MCP clients and panel chat cannot call `approve_plan`, `reject_plan` or `rollback_plan`.

The panel token authenticates a local process with access to your user account. It cannot prove that a person clicked. Keep credentials private and review the plan yourself. See [security](security.md) for this boundary.

### Can I turn off the approval gate?

`auto` and the panel's explicit Dev mode bypass approval checks. Use `ask_first` for the normal plan flow or `look_only` to refuse writes. Unknown mode values fall back to `ask_first`. See [configuration](configuration-reference.md).

## Compatibility

### Which Revit versions work?

The supported build targets are Revit 2024–2027 on Windows. The panel routes to its Revit instance; an MCP connection pins the selected discovered session. See [compatibility](compatibility.md) and [multi-Revit routing](0014-multi-revit-routing.md).

### Does it work on a Mac?

Live Revit requires Windows. Mock mode is plain Python; macOS behavior remains unverified. Linux CI is experimental.

### Which AI assistants work?

See [compatibility](compatibility.md) for documented clients and their test status. An installation example does not establish live client compatibility.

### Does it work offline?

The local server and add-in can run after installation without downloading anything. Most AI providers still need network access, as do the optional cloud tools. A fully local AI setup remains unverified.

### What is demo mode?

`MCP_REVIT_MODE=mock` uses built-in sample data. Write tools return mock responses and change no model. It is the default server mode when unset. Do not treat sample results as findings about your real model.

## Using it

### What can I ask it to do first?

Summarize the model, run the core QA check and list issues. Then try the approval flow in the [demo tutorial](getting-started.md).

### Has it been tested in a real Revit?

Bounded read-only checks are recorded in [live validation](revit-addin-live-validation-2026-10-14.md). Automated checks do not establish that every write works in Revit. Mutating acceptance remains pending; use a throwaway copy for the live tutorial.

### How do I undo a change?

Use Revit Undo immediately after the write, or review the panel rollback operation. `plan_revert` drafts a new approved change using recorded before values. Missing before values can prevent restoration; read `rollback_warnings` and verify with a fresh snapshot. See [proof and revert](proof-and-revert.md). These paths still need live acceptance.

### How do I know what was changed?

`get_proof_bundle` records the approved request and execution outcome. It does not independently inspect the resulting model. Take a fresh snapshot and compare it with Revit.

### What does UNVERIFIED mean?

The claim needs live acceptance or other evidence that the recorded tests do not supply. Treat it as a check to perform, rather than a promise.

### Where are my plans and files stored?

The workspace defaults to `Documents\AEC Model Bridge`. Plans, proofs and snapshots have their own subfolders. Set `MCP_REVIT_WORKSPACE_DIR` consistently for Revit, the panel hub and the MCP client if you choose another location.

## Maintenance and licence

### How do I update or uninstall it?

Close Revit before running a newer installer or uninstalling through Windows Apps. Remove the MCP client entry yourself if needed. The workspace contains project data and is separate from the program installation. See [install](install.md).

### What does it cost and what is the licence?

See [LICENSING.md](../LICENSING.md) for the existing GPL with Revit Linking Exception and commercial options. Your AI provider and Revit have their own terms and charges.

### Where do I report a bug or ask a question?

Use [Support](../SUPPORT.md), and include the details listed in [troubleshooting](troubleshooting.md#what-to-copy-into-a-bug-report). Report vulnerabilities privately as described in [SECURITY.md](../SECURITY.md).
