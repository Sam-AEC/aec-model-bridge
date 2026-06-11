# Build Task A8 — Parameterized provider contract tests

You are an autonomous implementation agent for AEC Model Bridge, working in an isolated git worktree on branch `task/A8-contract-tests`. Complete ONLY task A8, then stop.

## Read first
- `docs/agent-task-plan.md` (card A8) and `docs/system-blueprint-and-workflows.md` §10 standing practices
- `packages/mcp-server-revit/src/revit_mcp_server/providers/fake.py` and `providers/base.py` (the contract surface)
- `providers/registry.py`, `mcp_server.py` (which providers register in a clean offline env)
- `security/audit.py` (`redact_data`), existing `tests/test_providers.py` for fixtures/patterns

## Standing rules (binding)
1. Back-compat: production code changes only if a provider genuinely violates the contract — if so, fix minimally and flag it prominently in your summary.
2. Mock-first: the suite must pass offline with no credentials. Parameterize over providers that register in a clean environment (Revit mock, IFC, mapper, exporter, jobs, graph, fake; skip cloud/Rhino/proxy gracefully when their init prerequisites are absent — use pytest skip with reason, not silent omission).
3. No secrets in fixtures. 4. Touch only files this task needs. NEVER edit `docs/agent-task-plan.md` or `AGENT-TASK.md`.
5. Finish with ONE commit on the current branch, message starting `A8: `. Targeted `git add <paths>` only. Do not push.

## Environment setup
From repo root:
```
python -m venv packages/mcp-server-revit/.venv
packages/mcp-server-revit/.venv/Scripts/python -m pip install -e "packages/mcp-server-revit[dev]"
```
If `ifcopenshell` has no wheel for this Python, list versions with `py -0p` and recreate the venv with `py -3.12` or `py -3.11`.

## The task
Create `packages/mcp-server-revit/tests/test_provider_contract.py` — ONE suite parameterized over every registrable provider, asserting for each:
1. `identity` is a stable, non-empty string, unique across the registry.
2. The tool list is non-empty; tool names are unique globally (across all providers); every tool has a non-empty description.
3. Input schema: where the tool metadata carries a schema, it is valid JSON-schema-shaped (dict with `type` or `properties`); where the field doesn't exist, record that as an xfail/note rather than failing (follow reality).
4. Calling an unknown tool name raises a typed error (not a bare Exception or a string result).
5. Redaction: a synthetic result containing a fake bearer token, a Windows path, and a POSIX path passes through `redact_data` with all three redacted — run per provider result envelope shape.
6. Mutating-flag presence: assert the metadata field exists where defined; emit a single consolidated report (in test output) of providers/tools missing mutation metadata — informational, not failing (it becomes input for later manifest work).

If the contract in `base.py` differs from what the card assumes, follow reality and note the discrepancy in your final summary.

## Verify (must pass before committing)
```
packages/mcp-server-revit/.venv/Scripts/python -m pytest packages/mcp-server-revit/tests -k contract -v
packages/mcp-server-revit/.venv/Scripts/python -m pytest packages/mcp-server-revit/tests
```

## Deliverable
Final message: files changed, how many providers the suite parameterizes over (and which were skipped + why), test counts, any contract violations found in production code and how you handled them.
