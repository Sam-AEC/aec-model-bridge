using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using Microsoft.Web.WebView2.Core;
using RevitBridge.Bridge;
using Serilog;

namespace RevitBridge.UI
{
    public partial class BridgePanel : UserControl
    {
        private bool _initialized;
        private bool _pageReady;
        private readonly Queue<string> _pendingMessages = new Queue<string>();

        public BridgePanel()
        {
            InitializeComponent();
            Loaded += async (_, _) => await InitializeWebViewAsync();
        }

        private async Task InitializeWebViewAsync()
        {
            if (_initialized)
            {
                return;
            }

            _initialized = true;

            try
            {
                await Browser.EnsureCoreWebView2Async();
                Browser.CoreWebView2.WebMessageReceived += OnWebMessageReceived;
                Browser.CoreWebView2.NavigationCompleted += (_, _) =>
                {
                    _pageReady = true;
                    PostHostStatus();
                    FlushPendingMessages();
                };
                LoadPanelApp();
            }
            catch (Exception ex)
            {
                Log.Warning(ex, "WebView2 panel runtime is unavailable");
                Browser.Visibility = Visibility.Collapsed;
                Fallback.Visibility = Visibility.Visible;
                FallbackMessage.Text = "WebView2 runtime is unavailable. Install Microsoft Edge WebView2 Runtime and restart Revit.";
            }
        }

        private void OnWebMessageReceived(object? sender, CoreWebView2WebMessageReceivedEventArgs args)
        {
            string message;
            try
            {
                message = args.TryGetWebMessageAsString();
            }
            catch
            {
                message = args.WebMessageAsJson;
            }

            Log.Information("Bridge panel message received: {Message}", message);
            PostHostStatus();
        }

        private void PostHostStatus()
        {
            var dirtyCount = DocumentDirtyTracker.GetDirtyUniqueIds().Count;
            var payload = JsonSerializer.Serialize(new
            {
                type = "host.status",
                serverRunning = App.Server?.IsRunning == true,
                port = App.Server?.Port,
                revitVersion = App.RevitVersion,
                activeDocument = App.ActiveDocumentName,
                dirtyElementCount = dirtyCount,
                snapshotStale = dirtyCount > 0
            });

            Browser.CoreWebView2?.PostWebMessageAsJson(payload);
        }

        public void PostToPanel(object payload)
        {
            var json = JsonSerializer.Serialize(payload);
            if (!_pageReady || Browser.CoreWebView2 == null)
            {
                _pendingMessages.Enqueue(json);
                return;
            }

            Browser.CoreWebView2.PostWebMessageAsJson(json);
        }

        private void FlushPendingMessages()
        {
            while (_pendingMessages.Count > 0 && Browser.CoreWebView2 != null)
            {
                Browser.CoreWebView2.PostWebMessageAsJson(_pendingMessages.Dequeue());
            }
        }

        private void LoadPanelApp()
        {
            var panelPath = Path.Combine(AppContext.BaseDirectory, "panel", "index.html");
            if (File.Exists(panelPath))
            {
                Browser.Source = new Uri(panelPath);
                return;
            }

            Browser.NavigateToString(BuildShellHtml());
        }

        private static string BuildShellHtml()
        {
            return @"
<!doctype html>
<html lang=""en"">
<head>
  <meta charset=""utf-8"">
  <meta name=""viewport"" content=""width=device-width, initial-scale=1"">
  <style>
    :root { color-scheme: light dark; font-family: Segoe UI, system-ui, sans-serif; }
    body { margin: 0; min-height: 100vh; background: #f8fafc; color: #1f2937; }
    main { box-sizing: border-box; min-height: 100vh; padding: 18px; display: grid; gap: 14px; align-content: start; }
    header { border-bottom: 1px solid #d1d5db; padding-bottom: 12px; }
    h1 { margin: 0; font-size: 18px; line-height: 1.25; font-weight: 650; }
    p { margin: 6px 0 0; color: #4b5563; font-size: 12px; line-height: 1.5; }
    button { width: max-content; border: 0; border-radius: 6px; background: #2563eb; color: white; font: inherit; font-size: 13px; padding: 8px 12px; cursor: pointer; }
    button:hover { background: #1d4ed8; }
    pre { margin: 0; white-space: pre-wrap; word-break: break-word; border: 1px solid #d1d5db; border-radius: 6px; padding: 10px; background: white; color: #111827; font-size: 12px; }
    @media (prefers-color-scheme: dark) {
      body { background: #202124; color: #f3f4f6; }
      header { border-color: #3f3f46; }
      p { color: #cbd5e1; }
      pre { background: #111827; border-color: #374151; color: #e5e7eb; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <h1>AEC Model Bridge</h1>
      <p id=""state"">Panel host connected.</p>
    </header>
    <button id=""ping"" type=""button"">Refresh Host Status</button>
    <pre id=""status"">Waiting for host status...</pre>
  </main>
  <script>
    const statusEl = document.getElementById('status');
    const stateEl = document.getElementById('state');
    function post(message) {
      if (window.chrome && window.chrome.webview) {
        window.chrome.webview.postMessage(message);
      }
    }
    document.getElementById('ping').addEventListener('click', () => post('status.request'));
    window.chrome.webview.addEventListener('message', event => {
      stateEl.textContent = 'Host bridge active.';
      statusEl.textContent = JSON.stringify(event.data, null, 2);
    });
    post('panel.loaded');
  </script>
</body>
</html>";
        }
    }
}
