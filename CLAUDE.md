# AEC Model Bridge: notes for AI coding agents

Read this first; it exists so you do not have to rediscover the repo. Keep it short.

## Layout
- `packages/mcp-server-revit/` Python MCP server (package `revit_mcp_server`, Python 3.11+, `uv`). Almost all testable work happens here.
  - `src/revit_mcp_server/security/` approval gate (`approval.py`), proof/revert (`proof.py`), path safety (`safe_paths.py`: always build caller-supplied paths with `safe_child` / `snapshot_file`), workspace sandbox.
  - `src/revit_mcp_server/providers/` tool providers; `modules/<id>/` plug-in modules (`module.json` + `module.py`).
  - `tests/` pytest, ~3,600 tests, ~3 min.
- `packages/revit-bridge-addin/` C# Revit add-in (net48 / net8, Windows + Revit only; cannot be built or run in Linux CI containers).
- `panel/` approval panel (plain HTML/JS, WebView2). `docs/` user docs + ADRs (`docs/00NN-*.md`). `rule_packs/` QA rule packs.
- `scripts/` build, release, installer (PowerShell) and Python helpers (`version.py`, `count_tools.py`, `roadmap/score_features.py`).

## Commands (run from `packages/mcp-server-revit`)
```bash
uv sync --all-extras                       # once
uv run pytest -q -p no:cacheprovider       # full suite
uv run pytest -q tests/test_<area>.py      # run the narrowest file first, full suite once before committing
uv run ruff check src tests                # CI-enforced lint
uv run python scripts/generate_tool_docs.py  # after adding/changing tools; CI checks docs/tools-generated.md is current
python ../../scripts/version.py check      # version strings must agree (VERSION, pyproject, manifests)
```
`MCP_REVIT_MODE=mock` runs the server without Revit.

## Rules that reviewers enforce
- Writes to the model go through plans: `plan_actions` -> human approval -> `execute_plan`. Never add a write path that skips the gate.
- Fail closed. Refuse with a plain-language error rather than guessing.
- Do not claim live-Revit behaviour you did not observe; mark it as unverified (see `docs/release-checklist.md`).
- Every behaviour change: a test + a line under `## Unreleased` in `CHANGELOG.md`.
- Docs voice: plain, short sentences, no hype words.
- Commits reference issues (`Fixes #N`). Feature/fix work goes on its own branch; PRs target `dev`.

## Token budget: do not read these whole
`THIRD_PARTY_NOTICES.md` (365 KB), `uv.lock`, `docs/roadmap.md` (86 KB), `docs/tools-generated.md`,
`docs/security.md`, `docs/mcp-token-measurement-*.json`, `docs/i18n/`. Grep them or read a line range.
Use `-q` for pytest and `| tail` for long output.
