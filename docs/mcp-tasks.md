# MCP Tasks for long tool calls

Exports, snapshots, QA runs and `revit_run_job` can take minutes. A client that supports MCP Tasks can call these tools as a task: the server returns a task id at once, and the client polls the task, fetches the result or cancels it with the standard Tasks requests. A client that does not use Tasks calls the same tools exactly as before.

Tasks change how a result is delivered, not what a call may do. Every write still needs a plan that a person approves.

## Protocol support

The server uses the experimental Tasks API of the installed MCP Python SDK (`mcp` 1.30 or later, below 2). Tasks (SEP-1686) were removed from the core MCP specification and are expected to return as an MCP extension. The SDK marks its Tasks API deprecated for that reason, and mcp 2.0 is expected to remove it. The `mcp<2` pin in `pyproject.toml` keeps it available. Moving to mcp 2.x needs a port to the Tasks extension. If the SDK object has no experimental handler registry, the server starts without the Tasks requests.

At `initialize` the server advertises:

```json
"tasks": {"list": {}, "cancel": {}, "requests": {"tools": {"call": {}}}}
```

In `tools/list`, each tool that accepts a task has `"execution": {"taskSupport": "optional"}`. Other tools have no `execution` field. A client that does not know the field ignores it. The field adds 39 characters per tool: about 205 tokens (chars / 4) for the 21 tools in `full`, and about 20 tokens for the always-loaded set (`snapshot_take` and `snapshot_compute`). `enrich_tool` sets it, so `context_report` and `scripts/measure_mcp_tokens.py` count it.

Supported requests:

| Request | What it does |
| --- | --- |
| `tools/call` with `params.task` | Runs the call in the background and returns `CreateTaskResult` with `task.taskId`. |
| `tasks/get` | Returns the task status, a plain status message, `createdAt`, `lastUpdatedAt`, `ttl` and `pollInterval` (1000 ms). |
| `tasks/result` | Waits until the task has finished, then returns the same `CallToolResult` a direct call returns, with `_meta["io.modelcontextprotocol/related-task"]`. |
| `tasks/list` | Lists the tasks of the requesting session. |
| `tasks/cancel` | Cancels a task, with the limits below. |

`notifications/tasks/status` is not sent. Poll `tasks/get`.

## Tools that accept a task

The list is `TASK_TOOLS` in `packages/mcp-server-revit/src/revit_mcp_server/mcp_tasks.py`. A test checks that each name exists.

- Jobs: `revit_run_job`
- Exports: `revit_export`, `revit_export_dwg`, `revit_export_ifc`, `revit_export_image`, `revit_export_navisworks`
- Snapshots: `revit_extract_snapshot`, `snapshot_take`, `snapshot_compute`, `snapshot_diff`, `model_changes_compare_snapshots`
- QA runs: `qaqc_checker_run_check`, `revit_check_clashes`, `revit_cleanup_audit`, `model_bloat_audit`, `sheet_view_audit_run_audit`, `sheet_set_qa_check`, `links_worksets_audit_audit`, `ids_validator_validate_ifc`, `qa_handover_build_report`, `report_generator_build_review_pack`

A `tools/call` with `params.task` for any other tool is refused with error kind `task_not_supported`. Nothing runs and no approved action is used.

For `revit_run_job`, the task ends when the Revit job ends. The server keeps polling `revit_job_status` after the `wait_s` window, so the task result is the job's final state.

## How a task runs

1. The server checks the tool profile and the approval gate, exactly as for a direct call. A write claims its approved action here, before the task exists. A refused call returns an error result, not a task.
2. The call is queued in the shared job manager (the same one that runs `run_async` jobs) and the server returns the task.
3. When the call ends, the outcome is booked on the plan action as for a direct call, and the formatted result is kept for `tasks/result`.

Status mapping:

| Job state | Task status |
| --- | --- |
| queued, running | `working` |
| completed, tool result without `isError` | `completed` |
| completed with `isError`, or failed | `failed` |
| cancelled | `cancelled` |

A task is kept as long as its job: one hour after it finishes, and at most 128 finished jobs. A requested `ttl` above one hour is lowered to one hour. After that, `tasks/get` answers `Task not found`.

Task ids are scoped to the MCP session that created them. Another session gets `Task not found`.

## Cancellation

- Read-only call: `tasks/cancel` stops the task while it is queued or running. The server stops waiting; a request already sent to Revit may still finish there, with no effect on the model.
- Call that can change the model: `tasks/cancel` succeeds only while the task is still queued. The check and the cancel are one step in the job manager, so a write that has started is never stopped part way. A started write is refused with a message that the task keeps running; poll `tasks/get` for the outcome. In practice a write task starts almost at once, so most cancel requests for writes are refused.
- A write cancelled before it started did not change the model. Its approved action is booked as failed and cannot be reused; make a new plan to retry.
- A finished task cannot be cancelled; the request is refused.
- A job cancelled another way, for example with `job_cancel` or at server shutdown, shows as `cancelled` in `tasks/get`. If that job was a write that had started, the status message says to check the model before a retry.

A call counts as a write unless the approval gate would skip it (a read-only tool, or `revit_run_job` and `revit_execute_python` in `mode="read"`). When in doubt it counts as a write.

## Clients without Tasks

A `tools/call` without `params.task` takes the same path as before: same approval checks, same result text, same `run_async`, `job_status` and `job_cancel` behaviour. The only visible additions are the `tasks` server capability and the `execution` field on the tools listed above.

## Client support

None of these clients has been tested against this server with Tasks. Each entry is UNVERIFIED.

| Client | Calls tools as tasks |
| --- | --- |
| Claude Code | UNVERIFIED |
| Claude Desktop | UNVERIFIED |
| OpenAI Codex | UNVERIFIED |
| Cursor | UNVERIFIED |
| VS Code (GitHub Copilot) | UNVERIFIED |
| Cline, Gemini CLI, JetBrains, Visual Studio, Windsurf | UNVERIFIED |
| MCP Python SDK client (`session.experimental.call_tool_as_task`) | Tested in `tests/test_mcp_tasks.py` with the in-memory transport |

A client that ignores `execution.taskSupport` keeps calling the tools directly and can still use `run_async` with `job_status` and `job_cancel`.
