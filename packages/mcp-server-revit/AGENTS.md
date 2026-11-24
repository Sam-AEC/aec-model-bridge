# AGENTS.md: packages/mcp-server-revit

Root `AGENTS.md` applies. This file lists what differs here.

## Commands
Run from this directory.
```bash
uv sync --all-extras
uv run pytest -q -p no:cacheprovider
uv run ruff check src tests
uv run python scripts/generate_tool_docs.py   # rewrites ../../docs/tools-generated.md
python ../../scripts/count_tools.py           # tool counts used by docs and listing files
```

## Traps
- Tool counts appear in `README.md`, `llms.txt`, `docs/mcp-token-budget.md`, `server.json`, `manifest.json`, `glama.json`, `smithery.yaml` and the i18n READMEs. `tests/test_tool_count_claims.py` checks all of them. Adding a tool means updating each number.
- `tests/test_i18n_readmes.py` compares every translated README with `README.md`: code fences, heading counts, links and the language bar. Change README structure only with matching edits in `docs/i18n/`.
- `server.json` and `manifest.json` descriptions must be identical.
- A new tool needs: provider registration, a read or write flag (writes are gated), a test, and `docs/tools-generated.md` regenerated.
- Never open a caller-supplied path directly. Use `security/safe_paths.py`.
- Tests set `MCP_REVIT_MODE=mock` and a temporary workspace. Do not write to the real workspace.
- `uv.lock` must stay fresh (CI checks it). Run `uv lock` after changing dependencies.
