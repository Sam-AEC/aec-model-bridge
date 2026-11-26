# AEC Model Bridge

AEC Model Bridge is an open-source Revit MCP server (Model Context Protocol) with a native Revit add-in. AI clients such as Claude, Codex and Cursor read and edit BIM models through plans that a person approves.

- Mock mode runs the server without Revit, on any machine. It returns sample data.
- Live use needs Windows, Revit 2024 to 2027 and the AEC Model Bridge add-in.
- Every model change is a plan. A person approves it before it runs.

## Start here

- [Install](install.md): installer, source install and MCP client setup.
- [Tools reference](tools-generated.md): every tool with its arguments.
- [Security model](security.md) and [approval flow](adr/0008-approval-gate-lifecycle.md).
- [snapshot_compute](snapshot-compute.md): one-call queries on a saved model snapshot.
- [Read result cursors](read-cursors.md): size cap, cursors and saved results for large reads.
- [Prompt library](prompts/README.md): prompts to copy into your AI client.
- [Error catalogue](error-catalogue.md): error codes and what to do about each.
- [Configuration reference](configuration-reference.md): environment variables and settings.
- [Troubleshooting](troubleshooting.md).

The source, issues and releases are on [GitHub](https://github.com/Sam-AEC/aec-model-bridge).
