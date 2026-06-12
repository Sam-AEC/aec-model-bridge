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

- 2026-06-13 · If a card's instructions contradict reality (e.g., requested files already deleted), follow reality, note the discrepancy in the evidence line, and proceed.
- 2026-06-13 · File seeded during the Chapter 2 roadmap session (`docs/next-chapter.md`). Agents: append discoveries above this line.
