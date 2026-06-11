# Build Task A5 — Generated tool catalog

You are an autonomous implementation agent for AEC Model Bridge, working in an isolated git worktree on branch `task/A5-catalog`. Complete ONLY task A5, then stop.

## Read first
- `docs/agent-task-plan.md` (card A5) and `docs/system-blueprint-and-workflows.md` §2 rule 3 (manifests are the single source of truth)
- `packages/mcp-server-revit/src/revit_mcp_server/mcp_server.py` (how providers are registered; optional providers may fail init and be absent)
- `providers/base.py` (`ProviderTool` shape — check which metadata fields actually exist), `providers/registry.py`
- `docs/tools.md` (legacy hand-written catalog of the original 26 revit.* tools)
- `.github/workflows/ci.yml` (python job)

## Standing rules (binding)
1. Back-compat: existing tool names and configs untouched.
2. Mock-first: the generator must run offline with no credentials — providers that fail to initialize (cloud/Rhino) are listed in the output as "not initialized in this environment" rather than crashing the generator.
3. No secrets in output. 4. Touch only files this task needs. NEVER edit `docs/agent-task-plan.md` or `AGENT-TASK.md`.
5. Finish with ONE commit on the current branch, message starting `A5: `. Targeted `git add <paths>` only. Do not push.

## Environment setup
From repo root:
```
python -m venv packages/mcp-server-revit/.venv
packages/mcp-server-revit/.venv/Scripts/python -m pip install -e "packages/mcp-server-revit[dev]"
```
If `ifcopenshell` has no wheel for this Python, list versions with `py -0p` and recreate the venv with `py -3.12` or `py -3.11`.

## The task
1. Create `packages/mcp-server-revit/scripts/generate_tool_docs.py`: builds the provider registry the same way `mcp_server.py` does (mock mode, no credentials), introspects every registered provider, and writes `docs/tools-generated.md` — one section per provider with a table: tool name, description (first sentence), mutating? (emit `?` if the metadata field does not exist yet — note this in the file header), sync/async if known.
2. Output must be deterministic (stable sort) so reruns are byte-identical — this enables the CI drift check.
3. CI: in `.github/workflows/ci.yml` python job, add a step that runs the generator then `git diff --exit-code docs/tools-generated.md` (fails CI if the catalog drifted from code).
4. Add a short banner at the top of `docs/tools.md`: legacy document covering the original 26 tools; the complete generated catalog lives in `docs/tools-generated.md`.
5. Commit the generated `docs/tools-generated.md` (it should list all providers/tools available in a clean offline environment — expect roughly 7 providers and 120+ tools; cloud ones may be absent).

If `ProviderTool` lacks fields the card assumes, follow reality, degrade the column gracefully, and note the discrepancy in your final summary.

## Verify (must pass before committing)
```
packages/mcp-server-revit/.venv/Scripts/python packages/mcp-server-revit/scripts/generate_tool_docs.py
git diff --exit-code docs/tools-generated.md   (run generator twice; second run produces no diff)
packages/mcp-server-revit/.venv/Scripts/python -m pytest packages/mcp-server-revit/tests
```

## Deliverable
Final message: files changed, provider/tool counts in the generated catalog, test counts, discrepancies found.
