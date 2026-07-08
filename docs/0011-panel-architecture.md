# ADR 0011: WebView2 Dockable Panel & Hub Message Bridge

## Status
Accepted

## Context
Standard Revit add-ins built with WPF (Windows Presentation Foundation) suffer from development friction, lack of modern CSS/animation styling capabilities, and poor cross-platform portability. In addition, loading native assemblies into Revit's single-threaded app domain carries risk of thread locks and assembly load-order clashes. To deliver a modern, premium user interface (dark mode, glassmorphism, responsive chat, plan diff lists) that is portable across Revit, Rhino, and Navisworks, we need a WebView2-based panel architecture.

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

### 4. UI Design Philosophy & Frameworks
- **Styling**: Pure Vanilla CSS tailored with rich aesthetic HSL variables (sleek dark mode default, subtle micro-animations for hover states, glassmorphism card layouts).
- **No Heavy Frameworks**: Minimal javascript boilerplate; native Web Components or a lightweight view-scheduler (e.g., standard template strings) to avoid load-time lag.

## Consequences
- **Rapid Iteration**: UI changes, styling patches, and log viewer additions can be made and tested inside standard web browsers without needing to restart the Revit host application.
- **Cross-Platform Reusability**: The same WebView2 HTML code can be loaded into Rhino/Grasshopper panels or Navisworks UI containers, minimizing cross-platform code redundancy.
- **Runtime Requirement**: The client machine must have the Microsoft WebView2 Evergreen Runtime installed (shipped by default with Windows 10/11 and Microsoft 365 apps).
