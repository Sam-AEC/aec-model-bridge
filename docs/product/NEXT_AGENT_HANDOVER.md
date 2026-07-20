# Next Agent Handover

**Latest session:** 2026-07-20 — fixed the WebView2 panel's real Access-Denied bug (not the "environment conflict" the session before this one thought it was), built a CLI-backed chat surface into the panel, fixed a handful of real bugs that surfaced while proving it live, gave every ribbon button its own icon, and trimmed the README to match what's actually built.

**Read `git log` before trusting any summary here, including this one.** The session before this one wrote a commit message claiming it "reverted a custom WebView2 environment" — `git log -p` on `BridgePanel.xaml.cs` shows that line never actually changed across any commit; the revert never landed, and the panel had been silently broken the whole time. Verify against the log and the actual live logs (`%APPDATA%\AECModelBridge\Logs\bridge*.jsonl`), not the previous handover's word.

## What I did this session

### 1. Fixed the WebView2 panel for real

The live log showed the actual exception on every failed open: `System.UnauthorizedAccessException: Access is denied (0x80070005)` inside `CoreWebView2Environment.CreateAsync` — WebView2's default `UserDataFolder` sits next to the host executable (`Revit.exe` under `Program Files`), which a normal user can't write to. Fixed in `BridgePanel.xaml.cs`'s `InitializeWebViewAsync` by pointing `UserDataFolder` at `%LOCALAPPDATA%\AECModelBridge\WebView2` explicitly. This is Microsoft's documented pattern for any WebView2 host not launched from a writable directory — not a workaround.

### 2. Built a chat surface into the panel (personal-use scope, by explicit decision)

The panel's chat tab existed as UI scaffolding only (`panel/index.html`/`app.js`) with no backing tool — every message just said "Request sent to the host." Rather than build a custom LLM agent loop in Python, `agent_bridge.py` (new) shells out to whichever coding CLI is already installed and authenticated on the operator's machine (`claude` or `codex`), pointing it at this hub's own stdio MCP server via each CLI's own MCP-client mechanism. `panel_server.py` gained `POST /agent/chat`; `HubClient.cs`/`BridgePanel.xaml.cs` wired it through; `panel/app.js` got a provider dropdown and real request/response handling instead of the fake "sent" message.

**Explicitly out of scope for the general product**: this assumes the *operator's own* CLI session (their own Claude/Codex account, their own auth). Shipping this to other users needs a different trust model (bundled/managed CLI) — see the docstring at the top of `agent_bridge.py`. Do not extend this path to the general product surface without revisiting that.

**Verified live, not just unit-tested:**

- Claude path: proven repeatedly with real `revit_health` tool calls round-tripping through the actual hub, correct session continuity (`--resume`) across turns, honest error reporting when Revit's closed.
- Codex path: `codex mcp list` confirms `aec-model-bridge` is registered correctly and the same command-construction code is used — but on this machine, Codex CLI itself currently fails on *every* `codex exec` call (even ones with zero connection to this MCP server) because of an unrelated pre-existing broken MCP registration already in the operator's own `~/.codex/config.toml` (a `figma` server with a bad OAuth token). That's an environment problem for the operator to fix separately, not a bug in this code — confirmed by reproducing the identical failure with a bare `codex exec "hello"` call.

**Real bugs found and fixed while proving this live** (all reproduced directly, not theorized):

1. A second, stale full clone of this repo (`...\OneDrive\Documenten\GitHub\Autodesk-Revit-MCP-Server`, last commit from 2026-07-17) had an editable pip install shadowing *this* repo globally — every `python -m revit_mcp_server...` the add-in has ever launched via `PanelHubLauncher` was running that old checkout, not `development`. Re-ran `pip install -e` pointed at this repo. **If tool changes don't seem to take effect on this machine again, check `pip show aec-model-bridge` first.**
2. Claude Code's `--permission-mode acceptEdits` does not auto-approve MCP tool calls in headless (`-p`) mode — without an explicit `--allowedTools mcp__<server>` grant, every MCP tool call silently blocks, and the model sometimes fabricates a plausible-looking fake result instead of reporting the block. Fixed by adding the explicit grant.
3. Passing this process's own `sys.executable` (a WindowsApps App Execution Alias path) as the MCP server's launch command silently produces a session with no working tools when a *different* process (Claude Code's CLI) spawns it. Bare `"python"` resolved via PATH by the CLI's own spawner works reliably — matches `PanelHubLauncher.cs`'s existing convention, so `agent_bridge._mcp_server_command()` was changed to match rather than diverge.
4. `subprocess.run(["codex", ...])` (no `shell=True`) fails to find `codex` at all — it's an npm-installed `.CMD` shim on this machine, and Windows `CreateProcess` doesn't search `PATHEXT` for `.cmd`/`.bat` the way `shutil.which` (and a real shell) do. Fixed by resolving the full path via `shutil.which` once and using that, for both CLIs.
5. `mcp_server.py` takes ~2s just to import (Speckle/APS client init, etc.); without raising `MCP_TIMEOUT`, Claude Code sometimes gave up waiting for the MCP handshake and proceeded with zero Revit tools, silently. Fixed via `MCP_TIMEOUT=30000` in the subprocess env.
6. Windows subprocess default text encoding mangled em-dashes in Claude's replies (mojibake). Fixed via explicit `encoding="utf-8"`.

Tests: `packages/mcp-server-revit/tests/test_agent_bridge.py` (new, 10 tests, subprocess/shutil monkeypatched — no live CLI dependency in CI) plus the existing `test_panel_server.py`. Full suite: 225 passed, 4 skipped, ruff clean.

### 3. Ribbon icons: every button now has its own

`App.cs` was reusing the brand-logo icon for Open Panel, Pending Actions, *and* About simultaneously, the Status icon for both the Connection panel's Status button and Health Check, and the Settings gear for both Reports and Config. Added `CreatePanelIcon` (indigo dockable-panel glyph), `CreateHealthIcon` (amber clipboard+check), `CreatePendingIcon` (violet list+clock badge), and `CreateReportsIcon` (blue bar chart) to `IconGenerator.cs`, wired into `GenerateAllIcons()` and assigned in `App.cs`. About intentionally keeps the brand logo — that's the conventional choice, not leftover reuse.

### 4. README rewritten

Old copy oversold: a "Future roadmap" badge wall (Tekla, Archicad, Bentley iTwin, Trimble Connect, Procore, Primavera P6, SketchUp) and "Coming soon" entries (Solibri, Microsoft Graph, ACC, Forma) that don't exist anywhere in the actual phased backlog (`SCAFFOLDING_TASK_LIST.md`). Trimmed to the real four-app stack (Revit/Rhino/Navisworks/Power BI) plus what's genuinely near-term (Excel, Parquet/DuckDB), and rewrote the opening paragraph to state the actual thesis: one MCP call center an AI agent orchestrates directly, instead of a human copying data between apps by hand.

## What I did NOT change

- Did not wire `settings.save`, `reports.open`, or `reports.refresh` in the panel — still local-only, same as every prior session (no corresponding hub tool, or out of MVP scope).
- Did not touch `navisworks-bridge-addin`'s build story (still needs Sam's input per D-011/D-012).
- Did not extend the chat feature toward general-product shippability — see the explicit scope note above.
- Did not pursue the installer (Phase 19) or the façade configurator flagship demo (Phase 11), both flagged in the prior strategic conversation as the highest-leverage next moves for broader adoption — neither started.

## Exact next prompt

> Read docs/product/NEXT_AGENT_HANDOVER.md. The panel now has a working chat surface (Claude verified live, Codex correctly wired but blocked by an unrelated local Codex config issue) and every ribbon button has its own icon. Two directions flagged as high-leverage and not yet started: (1) a real installer (Phase 19 in SCAFFOLDING_TASK_LIST.md) — today's onboarding is git clone + manual venv + dotnet build from source, which blocks the primary BIM-coordinator persona from ever reaching the product; (2) the façade configurator flagship demo (Phase 11) — the shareable, differentiator proof point. Pick one with Sam, or continue wiring the panel's remaining local-only message types (settings.save, reports.open/refresh) if UI completeness is the priority instead. No Co-Authored-By trailers.
