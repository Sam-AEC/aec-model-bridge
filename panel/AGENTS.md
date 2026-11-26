# AGENTS.md: panel

Root `AGENTS.md` applies. This file lists what differs here.

## What this is
Plain HTML, CSS and JavaScript with no build step. The Revit add-in loads it in a WebView2 dockable pane (ADR `docs/adr/0011-panel-architecture.md`). The panel talks to the Python panel hub (`panel_server.py`, `127.0.0.1:8787`) through the add-in host bridge.

## Rules
- No bundler, no npm, no CDN. Vendored libraries and fonts live in `vendor/` with their licences and `VENDOR.txt`. The CSP allows fonts only from `'self'`.
- Approval and rejection are human-only. Do not add a code path that approves a plan without a click.
- Show plan arguments exactly as the hub returns them. Block approval when a review is malformed, unsupported or too large (`docs/security.md`, "Plan review in the panel").
- Follow Revit's light or dark theme. Colours come from `docs/design/tokens.md`.
- Never log or display the hub token.

## Testing
No JS test runner. The hub side is covered by `packages/mcp-server-revit/tests/test_panel_server.py`. For UI changes, open `panel/index.html` in a browser and check pending plans, approve, reject and the Setup check card. Say when a change was not run inside Revit.
