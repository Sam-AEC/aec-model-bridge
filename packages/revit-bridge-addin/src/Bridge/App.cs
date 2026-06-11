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
                    CreateModernRibbonInterface(application);
                }
                catch (Exception ex)
                {
                    Log.Error(ex, "Bridge started, but the AEC Model Bridge ribbon could not be created");
                }

                application.ControlledApplication.DocumentChanged += (sender, args) =>
                {
                    ActiveDocumentName = args.GetDocument()?.Title;
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

            string connectIconPath = Path.Combine(iconPath, "connect.png");
            string disconnectIconPath = Path.Combine(iconPath, "disconnect.png");
            string statusIconPath = Path.Combine(iconPath, "status.png");
            string brandIconPath = Path.Combine(iconPath, "brand.png");
            string settingsIconPath = Path.Combine(iconPath, "settings.png");
            string helpIconPath = Path.Combine(iconPath, "help.png");

            // Generate theme-adaptive icons, then retain in-memory fallbacks if file I/O fails.
            try
            {
                IconGenerator.GenerateAllIcons(iconPath);
            }
            catch (Exception ex)
            {
                Log.Error(ex, "Failed to dynamically generate ribbon icons");
            }

            BitmapSource connectIcon = LoadIcon(connectIconPath, IconGenerator.CreateConnectIcon);
            BitmapSource disconnectIcon = LoadIcon(disconnectIconPath, IconGenerator.CreateDisconnectIcon);
            BitmapSource statusIcon = LoadIcon(statusIconPath, IconGenerator.CreateStatusIcon);
            BitmapSource brandIcon = LoadIcon(brandIconPath, IconGenerator.CreateBrandIcon);
            BitmapSource settingsIcon = LoadIcon(settingsIconPath, IconGenerator.CreateSettingsIcon);
            BitmapSource helpIcon = LoadIcon(helpIconPath, IconGenerator.CreateHelpIcon);

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
            connectBtnData.Image = connectIcon;
            connectBtnData.LargeImage = connectIcon;
            connectBtnData.ToolTipImage = brandIcon;

            // Disconnect Button
            PushButtonData disconnectBtnData = new PushButtonData(
                "cmdDisconnect",
                "Disconnect",
                assemblyPath,
                "RevitBridge.Bridge.CommandDisconnect"
            );
            disconnectBtnData.ToolTip = "Stop the MCP Bridge Server";
            disconnectBtnData.LongDescription = "Stops AEC Model Bridge and closes all active connections.";
            disconnectBtnData.Image = disconnectIcon;
            disconnectBtnData.LargeImage = disconnectIcon;

            // Status Button
            PushButtonData statusBtnData = new PushButtonData(
                "cmdStatus",
                "Status",
                assemblyPath,
                "RevitBridge.Bridge.CommandStatus"
            );
            statusBtnData.ToolTip = "View Server Status and Statistics";
            statusBtnData.LongDescription = "Displays detailed information about the Bridge Server including connection status, statistics, and capabilities.";
            statusBtnData.Image = statusIcon;
            statusBtnData.LargeImage = statusIcon;

            // Create stacked items for better layout
            connectionPanel.AddItem(connectBtnData);
            connectionPanel.AddItem(disconnectBtnData);
            connectionPanel.AddSeparator();
            connectionPanel.AddItem(statusBtnData);

            // === TOOLS PANEL ===

            // Settings Button (future)
            PushButtonData settingsBtnData = new PushButtonData(
                "cmdSettings",
                "Config",
                assemblyPath,
                "RevitBridge.Bridge.CommandSettings"
            );
            settingsBtnData.ToolTip = "View Bridge Configuration";
            settingsBtnData.LongDescription = "View the local server address, runtime behavior, configuration path, and log path.";
            settingsBtnData.Image = settingsIcon;
            settingsBtnData.LargeImage = settingsIcon;
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
            helpBtnData.Image = helpIcon;
            helpBtnData.LargeImage = helpIcon;

            // About Button
            PushButtonData aboutBtnData = new PushButtonData(
                "cmdAbout",
                "About",
                assemblyPath,
                "RevitBridge.Bridge.CommandAbout"
            );
            aboutBtnData.ToolTip = "About AEC Model Bridge";
            aboutBtnData.LongDescription = "View the installed version, maintainer, documentation, and support links.";
            aboutBtnData.Image = brandIcon;
            aboutBtnData.LargeImage = brandIcon;

            toolsPanel.AddItem(settingsBtnData);
            toolsPanel.AddItem(helpBtnData);
            toolsPanel.AddSeparator();
            toolsPanel.AddItem(aboutBtnData);

            Log.Information("Modern ribbon interface created with icons");
        }

        private static BitmapSource LoadIcon(string path, Func<int, BitmapSource> fallbackFactory)
        {
            if (!File.Exists(path))
            {
                Log.Debug("Icon not found at {IconPath}; using generated fallback", path);
                return fallbackFactory(32);
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
