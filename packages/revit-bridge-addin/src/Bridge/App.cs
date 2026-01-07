using System;
using System.IO;
using Autodesk.Revit.UI;
using Serilog;

namespace RevitBridge.Bridge;

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

            // Create Ribbon UI
            CreateRibbonInterface(application);

            application.ControlledApplication.DocumentChanged += (sender, args) =>
            {
                ActiveDocumentName = args.GetDocument()?.Title;
            };

            Log.Information("RevitMCP Bridge started for Revit {Version}", RevitVersion);
            return Result.Succeeded;
        }
        catch (Exception ex)
        {
            Log.Fatal(ex, "Failed to start RevitMCP Bridge");
            return Result.Failed;
        }
    }

    private void CreateRibbonInterface(UIControlledApplication app)
    {
        string tabName = "RevitMCP";
        try
        {
            app.CreateRibbonTab(tabName);
        }
        catch (Autodesk.Revit.Exceptions.ArgumentException)
        {
            // Tab might already exist
        }

        RibbonPanel panel = app.CreateRibbonPanel(tabName, "Connection");

        string assemblyPath = System.Reflection.Assembly.GetExecutingAssembly().Location;

        // Connect Button
        PushButtonData connectBtnData = new PushButtonData(
            "cmdConnect",
            "Connect",
            assemblyPath,
            "RevitBridge.Bridge.CommandConnect");
        connectBtnData.ToolTip = "Start the MCP Bridge Server";
        
        // Disconnect Button
        PushButtonData disconnectBtnData = new PushButtonData(
            "cmdDisconnect",
            "Disconnect",
            assemblyPath,
            "RevitBridge.Bridge.CommandDisconnect");
        disconnectBtnData.ToolTip = "Stop the MCP Bridge Server";

        // Status Button
        PushButtonData statusBtnData = new PushButtonData(
            "cmdStatus",
            "Status",
            assemblyPath,
            "RevitBridge.Bridge.CommandStatus");
        statusBtnData.ToolTip = "Check Server Status";

        panel.AddItem(connectBtnData);
        panel.AddItem(disconnectBtnData);
        panel.AddSeparator();
        panel.AddItem(statusBtnData);
    }

    public Result OnShutdown(UIControlledApplication application)
    {
        try
        {
            _server?.Stop();
            _externalEvent?.Dispose();
            Log.Information("RevitMCP Bridge stopped");
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
            "RevitMCP", "Logs", "bridge.jsonl"
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
