using System;
using System.Collections.Generic;
using System.IO;

namespace RevitBridge.Bridge
{
    public class WorkspaceMonitor
    {
        private readonly List<string> _allowedDirectories = new();

        public WorkspaceMonitor()
        {
            var workspaceDir = Environment.GetEnvironmentVariable("MCP_REVIT_WORKSPACE_DIR");
            var allowedDirsEnv = Environment.GetEnvironmentVariable("MCP_REVIT_ALLOWED_DIRECTORIES");

            if (!string.IsNullOrEmpty(workspaceDir))
            {
                try
                {
                    _allowedDirectories.Add(Path.GetFullPath(workspaceDir));
                }
                catch { }
            }

            if (!string.IsNullOrEmpty(allowedDirsEnv))
            {
                foreach (var dir in allowedDirsEnv.Split(new[] { ';' }, StringSplitOptions.RemoveEmptyEntries))
                {
                    try
                    {
                        var fullPath = Path.GetFullPath(dir.Trim());
                        if (!_allowedDirectories.Contains(fullPath))
                        {
                            _allowedDirectories.Add(fullPath);
                        }
                    }
                    catch { }
                }
            }
        }

        public bool IsInWorkspace(string path)
        {
            if (string.IsNullOrEmpty(path)) return false;

            // If it doesn't look like a path (e.g. no directory separators and not rooted), skip validation
            if (!path.Contains(Path.DirectorySeparatorChar.ToString()) && 
                !path.Contains(Path.AltDirectorySeparatorChar.ToString()) && 
                !Path.IsPathRooted(path))
            {
                return true;
            }

            try
            {
                var fullPath = Path.GetFullPath(path);
                foreach (var allowedDir in _allowedDirectories)
                {
                    if (fullPath.StartsWith(allowedDir, StringComparison.OrdinalIgnoreCase))
                    {
                        if (fullPath.Length == allowedDir.Length ||
                            fullPath[allowedDir.Length] == Path.DirectorySeparatorChar ||
                            fullPath[allowedDir.Length] == Path.AltDirectorySeparatorChar)
                        {
                            return true;
                        }
                    }
                }
            }
            catch
            {
                return false;
            }

            return false;
        }

        public void AssertInWorkspace(string path)
        {
            if (!IsInWorkspace(path))
            {
                throw new UnauthorizedAccessException($"Path '{path}' is outside the allowed workspace directories.");
            }
        }
    }
}
