using System;
using System.Diagnostics;
using System.Reflection;

namespace RevitBridge
{
    internal static class ProductInfo
    {
        public const string ProductName = "AEC Model Bridge";
        public const string RepositoryUrl = "https://github.com/Sam-AEC/aec-model-bridge";
        public const string DocumentationUrl = RepositoryUrl + "#quick-start";
        public const string IssuesUrl = RepositoryUrl + "/issues";
        public const string GitHubProfileUrl = "https://github.com/Sam-AEC";
        public const string LinkedInUrl = "https://www.linkedin.com/in/a-sam-mohammad-92790416b";
        public const string MaintainerName = "A. Sam Mohammad";
        public const int McpToolCount = 100;

        public static string Version
        {
            get
            {
                var version = Assembly.GetExecutingAssembly().GetName().Version;
                return version == null
                    ? "Unknown"
                    : $"{version.Major}.{version.Minor}.{version.Build}";
            }
        }

        public static bool TryOpenUrl(string url, out string? error)
        {
            try
            {
                Process.Start(new ProcessStartInfo
                {
                    FileName = url,
                    UseShellExecute = true
                });
                error = null;
                return true;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                return false;
            }
        }
    }
}
