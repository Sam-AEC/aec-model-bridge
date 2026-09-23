# ADR 0011: WebView2 Dockable Panel & Hub Message Bridge

## Status
Accepted

## Context
Standard Revit add-ins built with WPF (Windows Presentation Foundation) suffer from development friction, lack of modern CSS/animation styling capabilities, and poor cross-platform portability. In addition, loading native assemblies into Revit's single-threaded app domain carries risk of thread locks and assembly load-order clashes. To deliver a modern user interface (a dark theme that follows Revit, restrained glass surfaces, responsive chat, a plan approval queue) that is portable across Revit, Rhino, and Navisworks, we need a WebView2-based panel architecture. The visual design has since shipped; §4 records what it is. `docs/design/tokens.md` is the concrete spec.

## Decisions

### 1. Panel Architecture Overview
The user interface is hosted inside a native C# WPF dockable pane using Revit's `IDockablePaneProvider` API. The panel hosts a Microsoft WebView2 runtime instance displaying a local web app:

```
┌────────────────────────────────────────────────────────┐
│                   Revit UI Shell                       │
│  ┌──────────────────────────────────────────────────┐  │
│  │  WPF Dockable Pane Chrome                        │  │
│  │  ┌────────────────────────────────────────────┐  │  │
│  │  │ WebView2 Browser Control                   │  │  │
│  │  │                                            │  │  │
│  │  │ UI Web App (HTML/JS/Vanilla CSS)           │  │  │
│  │  │ ────────────────────────────────────────── │  │  │
│  │  │ - Chat interface (conversational window)   │  │  │
│  │  │ - ActionPlan Card Queue (Approve/Reject)   │  │  │
│  │  │ - Live Run Ledger & Metrics                │  │  │
│  │  └────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

### 2. Double-Bridge Communication System
To maintain security boundaries while enabling rapid data transfer:

1. **Host Bridge (C# WebView2 Integration)**:
   - Communication from the Web App to the Revit C# add-in goes through WebView2's built-in message interface:
     - JS to C#: `window.chrome.webview.postMessage(JSON.stringify(payload))`
     - C# to JS: `webView.CoreWebView2.PostWebMessageAsString(payload)`
   - Used for UI-triggered host actions (e.g., highlighting an element by ID, selecting instances, zooming to bounding box).

2. **Hub Bridge (REST / MCP local loopback)**:
   - The Web App communicates with the Python hub via standard HTTP/JSON REST endpoints exposed by the hub's local server (running on a dynamic port published in `%LOCALAPPDATA%\AECModelBridge\registry\`).
   - The Web App queries:
     - `/plans/pending`: Active plans in the approval queue.
     - `/plans/{id}/approve`: Approves a plan for execution.
     - `/plans/{id}/reject`: Rejects a plan.
     - `/audit/logs`: Historical ledger entries for the active document.

### 3. Safety & Thread Isolation
- **Non-blocking UI**: The Web App runs entirely inside the isolated WebView2 process. Rendering complex graphs, SVG models, or parsing large log files does not block Revit's single-threaded user interface.
- **API Threading Dispatch**: Commands requiring access to Revit API objects are passed over the WebView2 Host Bridge, enqueued on `CommandQueue.Enqueue`, and raised via `ExternalEvent.Raise()` to execute on Revit's main API thread inside a standard Transaction.

### 4. UI Design System & Frameworks
- **Design tokens**: `docs/design/tokens.md` (approved) is the single source of truth for the brand mark, color, typography, surfaces, motion and the ribbon icon grammar. There is no codegen or token-sync tool. Values are hand-copied into `panel/styles.css` (as `--amb-*` CSS custom properties), `IconGenerator.cs` and `assets/logo.svg`, and each copy site carries a `keep in sync with docs/design/tokens.md` comment.
- **Brand mark**: "The Span", two bearings joined by a deck under a brand-colored apex. It replaces the three disagreeing cube/gradient marks. It appears as an inline SVG in the panel rail, as the ribbon brand icon, and in `assets/logo.svg`.
- **Theming**: Light and dark palettes, each with its own verified contrast. The panel follows **Revit's** theme, not only the OS theme. The add-in sends `isDarkTheme` (from `UIThemeManager.CurrentTheme`) in every `host.status` message, and `app.js` sets `data-theme` on `<html>`. `prefers-color-scheme` is only a fallback until the first `host.status` arrives. A mid-session Revit theme toggle re-themes the panel live: the add-in subscribes to Revit's `ThemeChanged` event (Revit 2024+, guarded for older versions) and sends a fresh `host.status`. Ribbon icons are the exception. They are generated once at startup, so they show the theme Revit had at session start and only change after a full Revit restart. This is a known, accepted limitation.
- **Surfaces**: Only two surfaces get the glass treatment: the topbar (`--amb-glass` fill plus `--amb-glass-filter`) and the rail (`--amb-glass-filter` over its always-dark `--amb-rail` fill). Cards, inputs and list rows stay opaque so body text stays legible. This narrows the original "glassmorphism card layouts" idea on purpose. Elevation uses two shadow tokens. A single `:focus-visible` ring is the universal focus affordance.
- **Semantic color**: One set of semantic tokens (danger, warning, info, success, pending, idle) drives both the panel badges and the ribbon icons. `pending` (plans waiting for approval) is violet on both.
- **Motion**: Two motion tokens (`--amb-motion-fast` for hover/press, `--amb-motion-view` for view switches). All animation and transitions are turned off under `prefers-reduced-motion: reduce`.
- **Typography**: Segoe UI / system-ui only, with no webfont. A webfont would flash each time the docked pane opens. Run-log timestamps use tabular numerals.
- **No Heavy Frameworks**: Vanilla HTML/CSS/JS with template strings, and no bundler, so the pane loads without lag.

## Consequences
- **Rapid Iteration**: UI changes, styling patches, and log viewer additions can be made and tested inside standard web browsers without needing to restart the Revit host application.
- **Cross-Platform Reusability**: The same WebView2 HTML code can be loaded into Rhino/Grasshopper panels or Navisworks UI containers, minimizing cross-platform code redundancy.
- **Runtime Requirement**: The client machine must have the Microsoft WebView2 Evergreen Runtime installed (shipped by default with Windows 10/11 and Microsoft 365 apps).
