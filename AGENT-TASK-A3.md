# Build Task A3 — Fix McpProxyProvider connect lifecycle

You are an autonomous implementation agent for AEC Model Bridge, working in an isolated git worktree on branch `task/A3-proxy`. Complete ONLY task A3, then stop.

## Read first
- `docs/agent-task-plan.md` (card A3) and `docs/system-blueprint-and-workflows.md` §0 + §9 item 2
- `packages/mcp-server-revit/src/revit_mcp_server/providers/proxy.py` — known defect: `_connect()` exists but is never called, so `_connected` stays `False` and every `execute_tool` raises `RuntimeError("ProxyProvider not connected")`
- `providers/base.py` (AECProvider contract), existing tests for patterns

## Standing rules (binding)
1. Back-compat: existing `revit_*` tool names, `revit.*` routes, `MCP_REVIT_*` env vars keep working.
2. Mock-first: all tests pass offline; no real SSE endpoints — use a fake/in-process server or stubbed transport.
3. No secrets/tokens in code, results, or logs.
4. Touch only files this task needs. **Scope guard:** do NOT register the provider in `mcp_server.py` — that is task A4, not yours. NEVER edit `docs/agent-task-plan.md` or `AGENT-TASK.md`.
5. Finish with ONE commit on the current branch, message starting `A3: `. Targeted `git add <paths>` only. Do not push.

## Environment setup
From repo root:
```
python -m venv packages/mcp-server-revit/.venv
packages/mcp-server-revit/.venv/Scripts/python -m pip install -e "packages/mcp-server-revit[dev]"
```
If `ifcopenshell` has no wheel for this Python, list versions with `py -0p` and recreate the venv with `py -3.12` or `py -3.11`.

## The task
1. Give the provider a real connect lifecycle: an async `initialize()` (called by the owner) AND/OR lazy connect on first `execute_tool`/`get_tools` — pick the pattern most consistent with `base.py` and document the choice in the docstring.
2. Add reconnect-with-exponential-backoff (bounded retries, jittered) when the SSE session drops mid-use; a clean typed error when the target is unreachable.
3. Surface the remote server's tool list into this provider's capability manifest (names namespaced to avoid collisions, preserving remote descriptions/schemas).
4. Graceful `shutdown()`/disconnect.
5. Tests with a fake MCP/SSE server (in-process): tools listed through proxy; tool call round-trip; one disconnect→reconnect cycle; unreachable-target error path. Use the `mcp` library's test utilities if convenient, otherwise stub the transport layer.

If the card contradicts the actual code, follow reality and note the discrepancy in your final summary.

## Verify (must pass before committing)
```
packages/mcp-server-revit/.venv/Scripts/python -m pytest packages/mcp-server-revit/tests -k proxy
packages/mcp-server-revit/.venv/Scripts/python -m pytest packages/mcp-server-revit/tests
```

## Deliverable
Final message: files changed, test counts, the lifecycle pattern chosen and why, discrepancies found.
