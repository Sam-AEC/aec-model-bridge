using System;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevitBridge;
using RevitBridge.UI;
using MediaColor = System.Windows.Media.Color;
using MediaBrush = System.Windows.Media.SolidColorBrush;

namespace RevitBridge.Bridge
{
    [Transaction(TransactionMode.Manual)]
    public class CommandSettings : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            ShowSettingsDialog();
            return Result.Succeeded;
        }

        private void ShowSettingsDialog()
        {
            var dialog = new ModernDialog();
            dialog.SetTitle("Bridge Configuration", "Current local settings");

            dialog.AddInfoSection("Server Configuration",
                "Address: http://127.0.0.1:3000/\n" +
                "Startup: Automatic with Revit\n" +
                "Transport: Localhost HTTP\n" +
                "Revit dispatch: ExternalEvent");

            dialog.AddSeparator();

            dialog.AddInfoSection("Features",
                "Universal bridge routes\n" +
                "Revit-safe main-thread execution\n" +
                "Audit logging\n" +
                "Batch operations\n" +
                "Reflection and in-process Python capabilities");

            dialog.AddSeparator();

            dialog.AddInfoSection("Advanced",
                "Distribution config:\n" +
                "C:\\ProgramData\\AECModelBridge\\config\\default.json\n\n" +
                "Bridge logs:\n" +
                "%APPDATA%\\AECModelBridge\\Logs\\bridge.jsonl");

            dialog.SetActionButton("OK");
            dialog.ShowDialog();
        }
    }

    [Transaction(TransactionMode.Manual)]
    public class CommandHelp : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            ShowHelpDialog();
            return Result.Succeeded;
        }

        private void ShowHelpDialog()
        {
            var dialog = new ModernDialog();
            dialog.SetTitle("AEC Model Bridge Help", "Documentation & Support");

            dialog.AddStatsGrid(
                ("MCP", "MCP tools", ProductInfo.McpToolCount.ToString()),
                ("API", "Bridge routes", BridgeCommandFactory.GetToolCatalog().Count.ToString()),
                (".NET", "Revit versions", "2024-2027")
            );

            dialog.AddSeparator();

            dialog.AddInfoSection("Quick Start",
                "1. Click 'Connect' to start the server\n" +
                "2. Use Claude Desktop or MCP client to connect\n" +
                "3. Start automating with natural language\n" +
                "4. Check 'Status' to monitor activity");

            dialog.AddSeparator();

            dialog.AddInfoSection("Available Commands",
                "Model authoring and inspection\n" +
                "Parameters, views, sheets, and schedules\n" +
                "Architecture, structure, and MEP\n" +
                "Exports, worksharing, and QA\n" +
                "Reflection and in-process Python");

            dialog.AddSeparator();

            dialog.AddInfoSection("Documentation",
                $"{ProductInfo.RepositoryUrl}\n" +
                "Use the links below for setup, documentation, and support.");

            dialog.AddInfoSection("Support",
                "Report reproducible defects and feature requests through GitHub Issues.");

            dialog.AddInfoSection("Licensing",
                "Version 1.1.0 and later is available under GPL-3.0-or-later with the " +
                "Revit Linking Exception, or under a separate commercial license. GPLv3 permits commercial and private " +
                "internal use. Its source and copyleft requirements apply when covered " +
                "software or combined derivative works are distributed. Contact the " +
                "maintainer for proprietary distribution rights or commercial support.");

            dialog.AddLinkButtons(
                ("Documentation", ProductInfo.DocumentationUrl),
                ("GitHub Issues", ProductInfo.IssuesUrl),
                ("Licensing", ProductInfo.LicensingUrl)
            );

            dialog.AddProfileSection(
                ProductInfo.MaintainerName,
                "Maintainer and commercial licensing contact",
                ProductInfo.MaintainerEmail,
                ProductInfo.GitHubProfileUrl,
                ProductInfo.LinkedInUrl
            );

            dialog.SetActionButton("Close");
            dialog.ShowDialog();
        }
    }

    [Transaction(TransactionMode.Manual)]
    public class CommandAbout : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            ShowAboutDialog();
            return Result.Succeeded;
        }

        private void ShowAboutDialog()
        {
            var dialog = new ModernDialog();
            dialog.SetTitle("About AEC Model Bridge", $"Version {ProductInfo.Version}");

            dialog.AddStatusCard(
                "MCP",
                "AEC Model Bridge",
                "Independent MCP integration for Revit software",
                new MediaBrush(MediaColor.FromRgb(33, 150, 243))
            );

            dialog.AddSeparator();

            dialog.AddInfoSection("Version Information",
                $"Version: {ProductInfo.Version}\n" +
                $"Revit: {App.RevitVersion ?? "Unknown"}\n" +
                "Platform: Revit-version-specific .NET runtime");

            dialog.AddSeparator();

            dialog.AddInfoSection("Features",
                $"{ProductInfo.McpToolCount} MCP tools\n" +
                $"{BridgeCommandFactory.GetToolCatalog().Count} active bridge routes\n" +
                "Architecture, structure, and MEP operations\n" +
                "Batch, export, and QA workflows\n" +
                "Universal reflection and in-process Python APIs");

            dialog.AddSeparator();

            dialog.AddInfoSection("Credits",
                $"Maintained by {ProductInfo.MaintainerName}\n" +
                "Built with Model Context Protocol and the Revit desktop API.\n\n" +
                "Copyright 2026 AEC Model Bridge Contributors\n\n" +
                "Not affiliated with or endorsed by Autodesk.");

            dialog.AddInfoSection("Licensing",
                "Version 1.1.0 and later is available under GPL-3.0-or-later with the " +
                "Revit Linking Exception, or under a separate commercial license. The GPL option permits use for any " +
                "purpose, including commercial and private internal use. A commercial " +
                "license is available for proprietary distribution or negotiated support.");

            dialog.AddLinkButtons(
                ("Repository", ProductInfo.RepositoryUrl),
                ("Licensing", ProductInfo.LicensingUrl)
            );

            dialog.AddProfileSection(
                ProductInfo.MaintainerName,
                "Maintainer and commercial licensing contact",
                ProductInfo.MaintainerEmail,
                ProductInfo.GitHubProfileUrl,
                ProductInfo.LinkedInUrl
            );

            dialog.SetActionButton("Close");
            dialog.ShowDialog();
        }
    }
}
