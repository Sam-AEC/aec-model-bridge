# AGENT.md — Accumulated Agent Learnings

Working notes written by agents for future agents. Append dated bullets under Learnings (newest first). Keep entries to one or two lines; this file is read at the start of every loop iteration.

## How to build and test

- Python hub tests: `python -m pytest packages/mcp-server-revit/tests`
- Dev install: `pip install -e packages/mcp-server-revit[dev]`
- Add-in build: `.\scripts\build-addin.ps1 -RevitVersion <2024|2025|2026|2027> -Configuration Release`
- Tool catalog regen (CI drift-checks this): `python packages/mcp-server-revit/scripts/generate_tool_docs.py`
- Backlog + rules: `docs/agent-task-plan.md` · Architecture: `docs/system-blueprint-and-workflows.md`

## Standing gotchas

- Scripts must be PowerShell 5.1 compatible: no `&&`, no ternary, no `?.`.
- Mock-first: CI must pass with no Revit/Navisworks installed; live tests only behind `AEC_LIVE_TESTS=1`.
- Secrets/tokens never appear in tool args, results, logs, or commits — extend `security/audit.py` redaction tests for anything new.
- Existing `revit_*` tool names, `revit.*` routes, and `MCP_REVIT_*` env vars must keep working (back-compat regression = failed task).

## Learnings

- 2026-06-13 · Navisworks 2026 API changes from earlier versions: `DocumentSavedViewpoints.ToGroupItem()` → `.RootItem`; `DocumentCurrentViewpoint.ToSavedItem()` → `doc.SavedViewpoints.CaptureRuntimeOverrides()`; `ClashResult.Selection1/2` is `ModelItemCollection` — use `.Item1/.Item2` (single `ModelItem`) instead; iterate `TestsData.Tests` as `SavedItem` and cast to `ClashTest` to access `TestType`/`Status`.
- 2026-06-13 · `BridgeCommandFactory` static constructor in Navisworks addin had a missing closing brace — all methods inside appeared to be inside the constructor, causing CS1513. Fix: ensure the constructor body closes before `CreateHandlerDelegate`.
- 2026-06-13 · When C# code uses `BridgeCommandAttribute`-based reflection discovery, every command class (e.g. `ClashCommands`) must be explicitly listed in the `types[]` array in the static constructor — it does NOT auto-discover subclasses.
- 2026-06-13 · Blueprint §3.2 result envelope (`ok`/`data`) differs from the legacy Revit bridge envelope (`Status`/`Result`). `BridgeClient.call_tool()` now handles both via `if "ok" in response` branching — backward-compat for Revit, correct for Navisworks.
- 2026-06-13 · When adding custom pytest markers (e.g. `@pytest.mark.perf`), register them in `pyproject.toml` under `[tool.pytest.ini_options]` `markers` to avoid warnings.
- 2026-06-13 · If a card's instructions contradict reality (e.g., requested files already deleted), follow reality, note the discrepancy in the evidence line, and proceed.
- 2026-06-13 · File seeded during the Chapter 2 roadmap session (`docs/next-chapter.md`). Agents: append discoveries above this line.
