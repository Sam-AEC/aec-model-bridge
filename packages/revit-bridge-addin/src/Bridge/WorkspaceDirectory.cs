using System;
using System.IO;

namespace RevitBridge.Bridge
{
    /// <summary>
    /// Single source of truth for the add-in's workspace directory. Must mirror the
    /// Python hub's Config.workspace_dir (config.py): MCP_REVIT_WORKSPACE_DIR when set,
    /// otherwise ~/Documents/AEC Model Bridge. UNVERIFIED against live Revit.
    /// </summary>
    public static class WorkspaceDirectory
    {
        public const string EnvVar = "MCP_REVIT_WORKSPACE_DIR";

        public static string Default()
        {
            var home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            return Path.Combine(home, "Documents", "AEC Model Bridge");
        }

        public static string Resolve()
        {
            var value = Environment.GetEnvironmentVariable(EnvVar);
            return string.IsNullOrWhiteSpace(value) ? Default() : value;
        }
    }
}
