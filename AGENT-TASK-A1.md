# Build Task A1 — Consolidate Speckle to a single provider

You are an autonomous implementation agent for AEC Model Bridge, working in an isolated git worktree on branch `task/A1-speckle`. Complete ONLY task A1, then stop.

## Read first
- `docs/agent-task-plan.md` (card A1) and `docs/system-blueprint-and-workflows.md` §0 + §9 item 1
- `packages/mcp-server-revit/src/revit_mcp_server/providers/speckle.py` (orphaned legacy provider, 2 tools, unregistered)
- `packages/mcp-server-revit/src/revit_mcp_server/providers/cloud.py` (registered SpeckleProvider: OAuth PKCE + GraphQL, 14 tools)
- `packages/mcp-server-revit/src/revit_mcp_server/mcp_server.py`, `tests/test_cloud_providers.py`

## Standing rules (binding)
1. Back-compat: existing `revit_*` tool names, `revit.*` routes, `MCP_REVIT_*` env vars keep working.
2. Mock-first: all tests must pass offline without licensed software; network calls mocked.
3. No secrets/tokens in code, test fixtures, results, or logs.
4. Touch only files this task needs. NEVER edit `docs/agent-task-plan.md` or `AGENT-TASK.md`.
5. Finish with ONE commit on the current branch, message starting `A1: `. Use targeted `git add <paths>` (never `git add -A`). Do not push.

## Environment setup
From repo root:
```
python -m venv packages/mcp-server-revit/.venv
packages/mcp-server-revit/.venv/Scripts/python -m pip install -e "packages/mcp-server-revit[dev]"
```
If `ifcopenshell` has no wheel for this Python, list versions with `py -0p` and recreate the venv with `py -3.12` or `py -3.11`.

## The task
1. Port the uniquely useful behavior from `providers/speckle.py` into the `SpeckleProvider` in `cloud.py`: a zero-OAuth fast path using Speckle Manager local credentials (`specklepy` `get_default_account()`), exposed as new tools `speckle_send_object` and `speckle_receive_object`. If no local account exists, raise a typed error with a clear message (do not return error strings as results).
2. Fix the legacy bug: model *name* must not be passed where a model **ID** is required — resolve name → ID via a models query first (mockable).
3. `speckle_receive_object` must deserialize and return actual object data (not just `get_member_names()`).
4. Replace any error-string-as-success returns with raised typed exceptions consistent with `errors.py` patterns.
5. Delete `providers/speckle.py`; clean up any imports/references (`__init__.py`, tests).
6. Tests (mocked, offline): name→ID resolution; send path; receive deserialization; no-local-account error path. Extend redaction coverage if any new fields could carry tokens.

If the card's description contradicts what you find in the code, follow reality and note the discrepancy in your final summary.

## Verify (must pass before committing)
```
packages/mcp-server-revit/.venv/Scripts/python -m pytest packages/mcp-server-revit/tests -k "speckle or cloud"
packages/mcp-server-revit/.venv/Scripts/python -m pytest packages/mcp-server-revit/tests
```

## Deliverable
Final message: files changed, test counts (passed/failed), discrepancies found, anything deliberately left out of scope.
