using System;
using System.Diagnostics;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
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
            dialog.SetTitle("Bridge Settings", "Configuration");

            dialog.AddInfoSection("Server Configuration",
                "Port: 3000\n" +
                "Host: localhost\n" +
                "Auto-start: Enabled\n" +
                "Logging: Enabled");

            dialog.AddSeparator();

            dialog.AddInfoSection("Features",
                "✅ Universal Bridge API\n" +
                "✅ Natural Language Processing\n" +
                "✅ Transaction Management\n" +
                "✅ Error Handling\n" +
                "✅ Batch Operations");

            dialog.AddSeparator();

            dialog.AddInfoSection("Advanced",
                "Note: Advanced settings can be configured in the config file.\n" +
                "Location: %AppData%\\AECModelBridge\\config.json");

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
                ("📘", "Tools", "233"),
                ("🎯", "Coverage", "99%"),
                ("⚡", "Commands", "143")
            );

            dialog.AddSeparator();

            dialog.AddInfoSection("Quick Start",
                "1. Click 'Connect' to start the server\n" +
                "2. Use Claude Desktop or MCP client to connect\n" +
                "3. Start automating with natural language\n" +
                "4. Check 'Status' to monitor activity");

            dialog.AddSeparator();

            dialog.AddInfoSection("Available Commands",
                "• Filtering (15 commands)\n" +
                "• Geometry (20 commands)\n" +
                "• Families (12 commands)\n" +
                "• MEP (10 commands)\n" +
                "• Structural (8 commands)\n" +
                "• Batch Operations (9 commands)\n" +
                "• Analysis & QA (7 commands)\n" +
                "• And many more...");

            dialog.AddSeparator();

            dialog.AddInfoSection("Documentation",
                "GitHub: github.com/Sam-AEC/aec-model-bridge\n" +
                "Docs: See README.md for full documentation");

            dialog.AddInfoSection("Support",
                "For issues and feature requests:\n" +
                "Create an issue on GitHub repository");

            dialog.SetActionButton("Open GitHub", () =>
            {
                try
                {
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = "https://github.com/Sam-AEC/aec-model-bridge",
                        UseShellExecute = true
                    });
                }
                catch { }
            });

            dialog.ShowCancelButton(() => { }); // Just close
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
            dialog.SetTitle("About AEC Model Bridge", "Version 1.0.1");

            dialog.AddStatusCard(
                "🏆",
                "AEC Model Bridge",
                "Independent MCP integration for Revit software",
                new MediaBrush(MediaColor.FromRgb(33, 150, 243))
            );

            dialog.AddSeparator();

            dialog.AddInfoSection("Version Information",
                "Version: 1.0.1\n" +
                $"Revit: {App.RevitVersion ?? "Unknown"}\n" +
                "Build: 2026.06.11\n" +
                "Platform: Revit-version-specific .NET runtime");

            dialog.AddSeparator();

            dialog.AddInfoSection("Features",
                "✅ 233 Available Tools\n" +
                "✅ 99% Workflow Coverage\n" +
                "✅ Natural Language Support\n" +
                "✅ All Disciplines (Arch, MEP, Structural)\n" +
                "✅ Batch Operations\n" +
                "✅ Quality Assurance Tools\n" +
                "✅ Universal Reflection API");

            dialog.AddSeparator();

            dialog.AddInfoSection("Credits",
                "Built with Model Context Protocol (MCP)\n" +
                "Revit API Integration\n\n" +
                "Copyright 2026 AEC Model Bridge Contributors\n\n" +
                "Not affiliated with or endorsed by Autodesk.");

            dialog.SetActionButton("Close");
            dialog.ShowDialog();
        }
    }
}
