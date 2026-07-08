using System;
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

        public static string? RevitVersion { get; private set; }
        public static string? ActiveDocumentName { get; private set; }
        public static BridgeServer? Server { get; private set; }

        public Result OnStartup(UIControlledApplication application)
        {
            try
            {
                InitializeLogging();

                RevitVersion = application.ControlledApplication.VersionNumber;

                _queue = new CommandQueue();
                var handler = new RevitCommandExecutor(_queue);
                _externalEvent = ExternalEvent.Create(handler);

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

                application.ControlledApplication.DocumentChanged += (sender, args) =>
                {
                    ActiveDocumentName = args.GetDocument()?.Title;
                    DocumentDirtyTracker.HandleDocumentChanged(sender, args);
                };
                application.ViewActivated += (sender, args) =>
                {
                    ActiveDocumentName = args.CurrentActiveView?.Document?.Title;
                    DocumentDirtyTracker.Clear();
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

            // Create panels
            RibbonPanel connectionPanel = app.CreateRibbonPanel(tabName, "Connection");
            RibbonPanel toolsPanel = app.CreateRibbonPanel(tabName, "Tools");

            string assemblyPath = System.Reflection.Assembly.GetExecutingAssembly().Location;

            // Use pre-existing icon files
            string iconPath = Path.Combine(
                Path.GetDirectoryName(assemblyPath) ?? "",
                "Icons"
            );

            string connectIconPath16 = Path.Combine(iconPath, "connect_16.png");
            string connectIconPath32 = Path.Combine(iconPath, "connect_32.png");
            string disconnectIconPath16 = Path.Combine(iconPath, "disconnect_16.png");
            string disconnectIconPath32 = Path.Combine(iconPath, "disconnect_32.png");
            string statusIconPath16 = Path.Combine(iconPath, "status_16.png");
            string statusIconPath32 = Path.Combine(iconPath, "status_32.png");
            string brandIconPath16 = Path.Combine(iconPath, "brand_16.png");
            string brandIconPath32 = Path.Combine(iconPath, "brand_32.png");
            string settingsIconPath16 = Path.Combine(iconPath, "settings_16.png");
            string settingsIconPath32 = Path.Combine(iconPath, "settings_32.png");
            string helpIconPath16 = Path.Combine(iconPath, "help_16.png");
            string helpIconPath32 = Path.Combine(iconPath, "help_32.png");

            // Generate theme-adaptive icons, then retain in-memory fallbacks if file I/O fails.
            try
            {
                IconGenerator.GenerateAllIcons(iconPath);
            }
            catch (Exception ex)
            {
                Log.Error(ex, "Failed to dynamically generate ribbon icons");
            }

            BitmapSource connectIcon16 = LoadIcon(connectIconPath16, IconGenerator.CreateConnectIcon, 16);
            BitmapSource connectIcon32 = LoadIcon(connectIconPath32, IconGenerator.CreateConnectIcon, 32);
            BitmapSource disconnectIcon16 = LoadIcon(disconnectIconPath16, IconGenerator.CreateDisconnectIcon, 16);
            BitmapSource disconnectIcon32 = LoadIcon(disconnectIconPath32, IconGenerator.CreateDisconnectIcon, 32);
            BitmapSource statusIcon16 = LoadIcon(statusIconPath16, IconGenerator.CreateStatusIcon, 16);
            BitmapSource statusIcon32 = LoadIcon(statusIconPath32, IconGenerator.CreateStatusIcon, 32);
            BitmapSource brandIcon16 = LoadIcon(brandIconPath16, IconGenerator.CreateBrandIcon, 16);
            BitmapSource brandIcon32 = LoadIcon(brandIconPath32, IconGenerator.CreateBrandIcon, 32);
            BitmapSource settingsIcon16 = LoadIcon(settingsIconPath16, IconGenerator.CreateSettingsIcon, 16);
            BitmapSource settingsIcon32 = LoadIcon(settingsIconPath32, IconGenerator.CreateSettingsIcon, 32);
            BitmapSource helpIcon16 = LoadIcon(helpIconPath16, IconGenerator.CreateHelpIcon, 16);
            BitmapSource helpIcon32 = LoadIcon(helpIconPath32, IconGenerator.CreateHelpIcon, 32);

            // === CONNECTION PANEL ===

            // Connect Button
            PushButtonData connectBtnData = new PushButtonData(
                "cmdConnect",
                "Connect",
                assemblyPath,
                "RevitBridge.Bridge.CommandConnect"
            );
            connectBtnData.ToolTip = "Start the MCP Bridge Server";
            connectBtnData.LongDescription = "Starts AEC Model Bridge to enable MCP automation for Revit software.";
            connectBtnData.Image = connectIcon16;
            connectBtnData.LargeImage = connectIcon32;
            connectBtnData.ToolTipImage = brandIcon32;

            // Disconnect Button
            PushButtonData disconnectBtnData = new PushButtonData(
                "cmdDisconnect",
                "Disconnect",
                assemblyPath,
                "RevitBridge.Bridge.CommandDisconnect"
            );
            disconnectBtnData.ToolTip = "Stop the MCP Bridge Server";
            disconnectBtnData.LongDescription = "Stops AEC Model Bridge and closes all active connections.";
            disconnectBtnData.Image = disconnectIcon16;
            disconnectBtnData.LargeImage = disconnectIcon32;

            // Status Button
            PushButtonData statusBtnData = new PushButtonData(
                "cmdStatus",
                "Status",
                assemblyPath,
                "RevitBridge.Bridge.CommandStatus"
            );
            statusBtnData.ToolTip = "View Server Status and Statistics";
            statusBtnData.LongDescription = "Displays detailed information about the Bridge Server including connection status, statistics, and capabilities.";
            statusBtnData.Image = statusIcon16;
            statusBtnData.LargeImage = statusIcon32;

            // Create stacked items for better layout
            connectionPanel.AddItem(connectBtnData);
            connectionPanel.AddItem(disconnectBtnData);
            connectionPanel.AddSeparator();
            connectionPanel.AddItem(statusBtnData);

            // === TOOLS PANEL ===

            // Open Panel Button
            PushButtonData panelBtnData = new PushButtonData(
                "cmdOpenPanel",
                "Open Panel",
                assemblyPath,
                "RevitBridge.Bridge.CommandOpenPanel"
            );
            panelBtnData.ToolTip = "Open the AEC Model Bridge panel";
            panelBtnData.LongDescription = "Shows the dockable AEC Model Bridge panel inside Revit.";
            panelBtnData.Image = brandIcon16;
            panelBtnData.LargeImage = brandIcon32;

            // Settings Button (future)
            PushButtonData settingsBtnData = new PushButtonData(
                "cmdSettings",
                "Config",
                assemblyPath,
                "RevitBridge.Bridge.CommandSettings"
            );
            settingsBtnData.ToolTip = "View Bridge Configuration";
            settingsBtnData.LongDescription = "View the local server address, runtime behavior, configuration path, and log path.";
            settingsBtnData.Image = settingsIcon16;
            settingsBtnData.LargeImage = settingsIcon32;
            settingsBtnData.AvailabilityClassName = "RevitBridge.Bridge.CommandAvailability";

            // Help Button
            PushButtonData helpBtnData = new PushButtonData(
                "cmdHelp",
                "Help",
                assemblyPath,
                "RevitBridge.Bridge.CommandHelp"
            );
            helpBtnData.ToolTip = "View Documentation";
            helpBtnData.LongDescription = "Open the AEC Model Bridge documentation and user guide.";
            helpBtnData.Image = helpIcon16;
            helpBtnData.LargeImage = helpIcon32;

            // About Button
            PushButtonData aboutBtnData = new PushButtonData(
                "cmdAbout",
                "About",
                assemblyPath,
                "RevitBridge.Bridge.CommandAbout"
            );
            aboutBtnData.ToolTip = "About AEC Model Bridge";
            aboutBtnData.LongDescription = "View the installed version, maintainer, documentation, and support links.";
            aboutBtnData.Image = brandIcon16;
            aboutBtnData.LargeImage = brandIcon32;

            toolsPanel.AddItem(panelBtnData);
            toolsPanel.AddSeparator();
            toolsPanel.AddItem(settingsBtnData);
            toolsPanel.AddItem(helpBtnData);
            toolsPanel.AddSeparator();
            toolsPanel.AddItem(aboutBtnData);

            Log.Information("Modern ribbon interface created with icons");
        }

        private static BitmapSource LoadIcon(
            string path,
            Func<int, BitmapSource> fallbackFactory,
            int size)
        {
            if (!File.Exists(path))
            {
                Log.Debug("Icon not found at {IconPath}; using generated fallback", path);
                return fallbackFactory(size);
            }

            var icon = new BitmapImage();
            icon.BeginInit();
            icon.CacheOption = BitmapCacheOption.OnLoad;
            icon.UriSource = new Uri(path, UriKind.Absolute);
            icon.EndInit();
            icon.Freeze();
            return icon;
        }

        public Result OnShutdown(UIControlledApplication application)
        {
            try
            {
                _server?.Stop();
                _externalEvent?.Dispose();
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
