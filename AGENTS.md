# AEC Model Bridge: agent instructions

Revit MCP server (Model Context Protocol) with a native Revit add-in. AI clients such as Claude, Codex and Cursor read and edit BIM models through plans that a person approves.

## Layout
- `packages/mcp-server-revit/`: Python MCP server (`revit_mcp_server`, Python 3.11+, `uv`). Most testable work is here.
  - `src/revit_mcp_server/security/`: approval gate (`approval.py`), proof and revert (`proof.py`), path safety (`safe_paths.py`), workspace sandbox. Build caller-supplied paths with `safe_child` or `snapshot_file`.
  - `src/revit_mcp_server/providers/`: tool providers. `modules/<id>/`: plug-in modules (`module.json` + `module.py`).
  - `tests/`: pytest, about 3,600 tests, about 3 minutes.
- `packages/revit-bridge-addin/`: C# Revit add-in (net48, net8, net10). Windows and Revit only; not buildable in Linux CI containers.
- `packages/vscode-extension/`: VS Code extension. `packages/claude-plugin/`: Claude Code plugin (listed by `.claude-plugin/marketplace.json`).
- `panel/`: approval panel (plain HTML and JS in WebView2).
- `docs/`: reference docs and ADRs (`docs/adr/00NN-*.md`). `docs/examples/rule_packs/`: example QA rule packs.
- `scripts/`: PowerShell build, release and installer scripts; Python helpers (`version.py`, `count_tools.py`, `sync_counts.py`, `changelog.py`, `make_install_links.py`).

## Commands
Run from `packages/mcp-server-revit`:
```bash
uv sync --all-extras
uv run pytest -q -p no:cacheprovider        # full suite
uv run pytest -q tests/test_<area>.py       # narrowest file first; full suite once before committing
uv run ruff check src tests                 # CI lint
uv run python scripts/generate_tool_docs.py # after adding or changing tools; CI checks docs/tools-generated.md
python ../../scripts/version.py check       # VERSION, pyproject and manifests must agree
```
`MCP_REVIT_MODE=mock` runs the server without Revit.

## Rules
- Model writes go through plans: `plan_actions`, human approval, `execute_plan`. Never add a write path that skips the gate.
- Fail closed. Refuse with a plain-language error instead of guessing.
- Do not claim live-Revit behaviour you did not observe. Mark it UNVERIFIED (see `docs/release-checklist.md`).
- Every behaviour change needs a test and one fragment file `changes/<issue-or-branch>.md` (see `changes/README.md`); do not edit `CHANGELOG.md`. After adding or removing a tool run `python scripts/sync_counts.py` and `python scripts/make_llms_full.py`.
- Docs: plain, short, factual sentences. No hype words, no emoji, no personal data, no dated narrative.
- Commits reference issues (`Fixes #N`). Work on its own branch; PRs target `dev`. PRs into `dev` are squash-merged; `dev` into `main` uses a merge commit.
- Before taking an issue, read its comments and assignees. Skip issues labelled `claimed` or assigned to someone; a contributor who asks to take one gets assigned and labelled `claimed`.
- While a release PR (`dev` into `main`) is open, `dev` is frozen: merge nothing into `dev` until it lands.
- `README.md` and `docs/i18n/README.*.md` are for humans. Every other doc is written for agents and search. Tests check README structure, tool counts and links, so run the full suite after editing docs.

## Do not read whole
`THIRD_PARTY_NOTICES.md` (365 KB), `uv.lock`, `docs/tools-generated.md`, `docs/security.md`, `docs/mcp-token-budget.md`, `docs/i18n/`. Grep them or read a line range. Use `pytest -q` and `| tail` for long output.
