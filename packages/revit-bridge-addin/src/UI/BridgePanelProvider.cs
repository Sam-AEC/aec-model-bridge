using System;
using Autodesk.Revit.UI;
using Serilog;

namespace RevitBridge.UI
{
    public class BridgePanelProvider : IDockablePaneProvider
    {
        public static readonly DockablePaneId PaneId = new DockablePaneId(
            new Guid("4E6D3F28-1C74-4B41-9B6E-7B1D3A2C0C4F"));

        private static BridgePanel? _panel;
        private static object? _pendingPayload;

        public static void Register(UIControlledApplication application)
        {
            application.RegisterDockablePane(PaneId, "AEC Model Bridge", new BridgePanelProvider());
            Log.Information("AEC Model Bridge dockable pane registered");

            // Guarded like IconGenerator.IsDarkTheme(): ThemeChanged only exists on
            // Revit 2024+. The reference lives in its own non-inlined method so a
            // missing event surfaces as a catchable MissingMemberException here
            // rather than a JIT failure of Register itself.
            try
            {
                SubscribeToThemeChanged(application);
            }
            catch (Exception ex)
            {
                Log.Information(ex, "Revit theme-change event unavailable; panel theme syncs on next host status only");
            }
        }

        [System.Runtime.CompilerServices.MethodImpl(System.Runtime.CompilerServices.MethodImplOptions.NoInlining)]
        private static void SubscribeToThemeChanged(UIControlledApplication application)
        {
            // Push a fresh host.status (which carries isDarkTheme) the moment the
            // user toggles Revit's theme, instead of waiting for their next click.
            application.ThemeChanged += (_, _) => _panel?.OnRevitThemeChanged();
        }

        public static bool Show(UIApplication application, out string error, string view = "", string action = "")
        {
            try
            {
                application.GetDockablePane(PaneId).Show();
                if (!string.IsNullOrWhiteSpace(view) || !string.IsNullOrWhiteSpace(action))
                {
                    var payload = new
                    {
                        type = "panel.view",
                        view,
                        action
                    };

                    if (_panel != null)
                    {
                        _panel.PostToPanel(payload);
                    }
                    else
                    {
                        _pendingPayload = payload;
                    }
                }

                error = "";
                return true;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                Log.Warning(ex, "Failed to show AEC Model Bridge dockable pane");
                return false;
            }
        }

        public void SetupDockablePane(DockablePaneProviderData data)
        {
            _panel = new BridgePanel();
            if (_pendingPayload != null)
            {
                _panel.PostToPanel(_pendingPayload);
                _pendingPayload = null;
            }

            data.FrameworkElement = _panel;
            data.InitialState = new DockablePaneState
            {
                DockPosition = DockPosition.Right
            };
        }
    }
}
