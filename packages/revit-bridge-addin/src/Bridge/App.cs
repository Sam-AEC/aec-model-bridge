using System;
using System.Collections.Generic;
using System.IO;
using System.Windows.Media.Imaging;
using Autodesk.Revit.UI;
using RevitBridge;
using RevitBridge.UI;
using Serilog;

namespace RevitBridge.Bridge
{
    public class App : IExternalApplication
    {
        private BridgeServer? _server;
        private CommandQueue? _queue;
        private ExternalEvent? _externalEvent;
        private PanelHubLauncher? _hubLauncher;

        public static string? RevitVersion { get; private set; }
        public static string? ActiveDocumentName { get; private set; }
        public static BridgeServer? Server { get; private set; }

        public Result OnStartup(UIControlledApplication application)
        {
            try
            {
                InitializeLogging();

                RevitVersion = application.ControlledApplication.VersionNumber;

                // Build the command table now (#291): a duplicate [BridgeCommand] name throws here, is
                // logged as fatal below and stops the bridge, instead of failing on the first request.
                Log.Information("Bridge command table: {Count} commands", BridgeCommandFactory.GetToolCatalog().Count);

                _queue = new CommandQueue();
                var handler = new RevitCommandExecutor(_queue);
                _externalEvent = ExternalEvent.Create(handler);
                handler.Event = _externalEvent;

                _server = new BridgeServer(_queue, _externalEvent);
                Server = _server; // Expose statically
                _server.Start();

                try
                {
                    BridgePanelProvider.Register(application);
                }
                catch (Exception ex)
                {
                    Log.Error(ex, "Bridge started, but the AEC Model Bridge dockable pane could not be registered");
                }

                try
                {
                    CreateModernRibbonInterface(application);
                }
                catch (Exception ex)
                {
                    Log.Error(ex, "Bridge started, but the AEC Model Bridge ribbon could not be created");
                }

                try
                {
                    // Fire-and-forget: checks/launches in the background, never blocks startup.
                    _hubLauncher = new PanelHubLauncher();
                    _hubLauncher.EnsureRunning();
                }
                catch (Exception ex)
                {
                    Log.Error(ex, "Bridge started, but the panel hub could not be launched");
                }

                application.ControlledApplication.DocumentChanged += (sender, args) =>
                {
                    ActiveDocumentName = args.GetDocument()?.Title;
                    DocumentDirtyTracker.HandleDocumentChanged(sender, args);
                    ElementLookup.OnDocumentChanged(args);
                };
                application.ControlledApplication.DocumentClosing += (sender, args) =>
                {
                    ElementLookup.OnDocumentClosing(args);
                };
                // Incremental snapshots (issue 290) trust the change journal only while it saw every
                // change. These events load changes that may not raise DocumentChanged, or give the
                // document a new identity, so they start a new journal epoch (next snapshot is full).
                var controlled = application.ControlledApplication;
                controlled.DocumentOpened += (sender, args) => DocumentDirtyTracker.ResetDocument(args.Document);
                controlled.DocumentClosing += (sender, args) => DocumentDirtyTracker.ResetDocument(args.Document);
                controlled.DocumentSynchronizedWithCentral += (sender, args) => DocumentDirtyTracker.ResetDocument(args.Document);
                controlled.DocumentReloadedLatest += (sender, args) => DocumentDirtyTracker.ResetDocument(args.Document);
                controlled.DocumentSavedAs += (sender, args) => DocumentDirtyTracker.ResetDocument(args.Document);
                application.ViewActivated += (sender, args) =>
                {
                    ActiveDocumentName = args.CurrentActiveView?.Document?.Title;
                    ElementLookup.OnViewActivated(args);
                    // Do NOT clear dirty tracker here — it must persist until after a
                    // successful revit_extract_snapshot so get_snapshot_delta has a
                    // complete list. Clearing on view activation dropped the entire
                    // delta whenever the user switched views after editing (H3 fix).
                };

                Log.Information("AEC Model Bridge started for Revit {Version}", RevitVersion);
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                Log.Fatal(ex, "Failed to start AEC Model Bridge");
                _server?.Stop();
                _externalEvent?.Dispose();
                return Result.Failed;
            }
        }

        private void CreateModernRibbonInterface(UIControlledApplication app)
        {
            string tabName = "AEC Bridge";
            try
            {
                app.CreateRibbonTab(tabName);
            }
            catch (Autodesk.Revit.Exceptions.ArgumentException)
            {
                // Tab might already exist
            }

            RibbonPanel bridgePanel = app.CreateRibbonPanel(tabName, "Model Bridge");
            RibbonPanel connectionPanel = app.CreateRibbonPanel(tabName, "Connection");

            string assemblyPath = System.Reflection.Assembly.GetExecutingAssembly().Location;
            BitmapSource brandIcon32 = IconGenerator.CreateBrandIcon(32);

            PushButtonData Define(
                string name,
                string text,
                string command,
                string toolTip,
                string description,
                Func<int, BitmapSource> icon)
            {
                var data = new PushButtonData(name, text, assemblyPath, command)
                {
                    ToolTip = toolTip,
                    LongDescription = description,
                    Image = icon(16),
                    LargeImage = icon(32),
                    ToolTipImage = brandIcon32
                };
                data.SetContextualHelp(new ContextualHelp(ContextualHelpType.Url, ProductInfo.DocumentationUrl));
                return data;
            }

            PushButtonData panelBtnData = Define(
                "cmdOpenPanel", "Panel", "RevitBridge.Bridge.CommandOpenPanel",
                "Open the AEC Model Bridge panel",
                "Shows the dockable AEC Model Bridge panel inside Revit.",
                IconGenerator.CreatePanelIcon);

            PushButtonData approveBtnData = Define(
                "cmdReviewPendingActions", "Approve", "RevitBridge.Bridge.CommandReviewPendingActions",
                "Review pending plans",
                "Opens the approval queue in the AEC Model Bridge panel.",
                IconGenerator.CreateApproveIcon);

            PushButtonData healthBtnData = Define(
                "cmdRunHealthCheck", "Check model", "RevitBridge.Bridge.CommandRunHealthCheck",
                "Check the model",
                "Opens the findings view and requests a QA/QC health check.",
                IconGenerator.CreateHealthIcon);

            PushButtonData connectionBtnData = Define(
                "cmdToggleConnection", ConnectionText(), "RevitBridge.Bridge.CommandToggleConnection",
                ConnectionToolTip(),
                "Starts or stops the local MCP bridge server. The button shows the current state.",
                ConnectionIcon);

            PushButtonData statusBtnData = Define(
                "cmdStatus", "Status", "RevitBridge.Bridge.CommandStatus",
                "View server status",
                "Displays detailed information about the Bridge Server including connection status, statistics, and capabilities.",
                IconGenerator.CreateStatusIcon);

            PushButtonData settingsBtnData = Define(
                "cmdSettings", "Config", "RevitBridge.Bridge.CommandSettings",
                "View bridge configuration",
                "View the local server address, runtime behavior, configuration path, and log path.",
                IconGenerator.CreateSettingsIcon);
            settingsBtnData.AvailabilityClassName = "RevitBridge.Bridge.CommandAvailability";

            PushButtonData reportsBtnData = Define(
                "cmdReports", "Reports", "RevitBridge.Bridge.CommandOpenReports",
                "Open report tools",
                "Opens report export controls in the AEC Model Bridge panel.",
                IconGenerator.CreateReportsIcon);

            PushButtonData helpBtnData = Define(
                "cmdHelp", "Help", "RevitBridge.Bridge.CommandHelp",
                "Open the documentation",
                "Open the AEC Model Bridge documentation and user guide.",
                IconGenerator.CreateHelpIcon);

            PushButtonData aboutBtnData = Define(
                "cmdAbout", "About", "RevitBridge.Bridge.CommandAbout",
                "About AEC Model Bridge",
                "View the installed version, maintainer, documentation, and support links.",
                IconGenerator.CreateAboutIcon);

            // Model Bridge: the three everyday actions.
            Track(bridgePanel.AddItem(panelBtnData), IconGenerator.CreatePanelIcon);
            Track(bridgePanel.AddItem(approveBtnData), IconGenerator.CreateApproveIcon);
            Track(bridgePanel.AddItem(healthBtnData), IconGenerator.CreateHealthIcon);

            // Connection: one toggle, the rest in the slide-out.
            _connectionButton = connectionPanel.AddItem(connectionBtnData) as PushButton;
            Track(_connectionButton, ConnectionIcon);

            // No Dev panel: the add-in has no reliable signal for Dev mode (the hub signs .dev-mode.json
            // and only the hub can verify it), so Reports sits in the slide-out.
            connectionPanel.AddSlideOut();
            Track(connectionPanel.AddItem(statusBtnData), IconGenerator.CreateStatusIcon);
            Track(connectionPanel.AddItem(settingsBtnData), IconGenerator.CreateSettingsIcon);
            Track(connectionPanel.AddItem(reportsBtnData), IconGenerator.CreateReportsIcon);
            Track(connectionPanel.AddItem(helpBtnData), IconGenerator.CreateHelpIcon);
            Track(connectionPanel.AddItem(aboutBtnData), IconGenerator.CreateAboutIcon);

            Log.Information("Modern ribbon interface created with icons");
        }

        private static PushButton? _connectionButton;

        private static bool IsConnected => Server?.IsListening == true;

        private static string ConnectionText() => IsConnected ? "Connected" : "Disconnected";

        private static string ConnectionToolTip() =>
            IsConnected ? "Connected. Click to stop the bridge server" : "Disconnected. Click to start the bridge server";

        private static BitmapSource ConnectionIcon(int size) =>
            IsConnected ? IconGenerator.CreateConnectedIcon(size) : IconGenerator.CreateDisconnectedIcon(size);

        /// <summary>Updates the Connection button text, tooltip and icon after the server starts or stops.</summary>
        internal static void RefreshConnectionButton()
        {
            var button = _connectionButton;
            if (button == null)
            {
                return;
            }

            try
            {
                button.ItemText = ConnectionText();
                button.ToolTip = ConnectionToolTip();
                button.Image = ConnectionIcon(16);
                button.LargeImage = ConnectionIcon(32);
            }
            catch (Exception ex)
            {
                Log.Debug(ex, "Could not refresh the connection button");
            }
        }

        private static readonly List<(PushButton Button, Func<int, BitmapSource> Factory)> ThemedButtons =
            new List<(PushButton, Func<int, BitmapSource>)>();

        private static void Track(RibbonItem? item, Func<int, BitmapSource> factory)
        {
            if (item is PushButton button)
            {
                ThemedButtons.Add((button, factory));
            }
        }

        /// <summary>Redraws every ribbon icon for the current Revit theme (called from ThemeChanged).</summary>
        internal static void RefreshRibbonIcons()
        {
            foreach (var (button, factory) in ThemedButtons)
            {
                try
                {
                    button.Image = factory(16);
                    button.LargeImage = factory(32);
                }
                catch (Exception ex)
                {
                    Log.Debug(ex, "Could not refresh ribbon icon for {Button}", button.Name);
                }
            }
        }

        public Result OnShutdown(UIControlledApplication application)
        {
            try
            {
                _hubLauncher?.StopIfLaunched();
                _server?.Stop();
                _externalEvent?.Dispose();
                PythonScriptRunner.ShutdownEngine();
                Log.Information("AEC Model Bridge stopped");
                Log.CloseAndFlush();
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                Log.Error(ex, "Error during shutdown");
                return Result.Failed;
            }
        }

        private void InitializeLogging()
        {
            var logPath = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "AECModelBridge", "Logs", "bridge.jsonl"
            );

            Directory.CreateDirectory(Path.GetDirectoryName(logPath)!);

            Log.Logger = new LoggerConfiguration()
                .WriteTo.File(
                    logPath,
                    rollingInterval: RollingInterval.Day,
                    outputTemplate: "{Timestamp:yyyy-MM-dd HH:mm:ss.fff zzz} [{Level:u3}] {Message:lj}{NewLine}{Exception}"
                )
                .CreateLogger();
        }
    }

    /// <summary>
    /// Command availability controller (for future use)
    /// </summary>
    public class CommandAvailability : IExternalCommandAvailability
    {
        public bool IsCommandAvailable(UIApplication applicationData, Autodesk.Revit.DB.CategorySet selectedCategories)
        {
            // For now, always available
            return true;
        }
    }
}
