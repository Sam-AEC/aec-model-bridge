using System;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace RevitBridge.UI
{
    /// <summary>
    /// Calls the Python MCP hub's local panel HTTP shim (packages/mcp-server-revit's
    /// panel_server.py). MCP itself is stdio-only — a WebView2 page cannot launch or
    /// speak to a stdio subprocess — so per docs/product/PLUGIN_APP_ARCHITECTURE.md
    /// section 2 the panel reaches the hub over a small loopback HTTP shim instead.
    /// This is the one piece of the add-in that bridges that gap.
    /// </summary>
    internal static class HubClient
    {
        private static readonly HttpClient Client = new HttpClient { Timeout = TimeSpan.FromSeconds(30) };

        private static int Port
        {
            get
            {
                var raw = Environment.GetEnvironmentVariable("MCP_PANEL_HTTP_PORT");
                return int.TryParse(raw, out var port) ? port : 8787;
            }
        }

        public static async Task<HubResult> ExecuteToolAsync(string tool, object arguments)
        {
            var requestBody = JsonSerializer.Serialize(new { tool, arguments });

            try
            {
                using (var content = new StringContent(requestBody, Encoding.UTF8, "application/json"))
                using (var response = await Client.PostAsync($"http://127.0.0.1:{Port}/execute", content).ConfigureAwait(false))
                {
                    var text = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
                    return ParseResponse(text, (int)response.StatusCode);
                }
            }
            catch (Exception ex)
            {
                return HubResult.Failure($"Could not reach the AEC Model Bridge hub on 127.0.0.1:{Port}: {ex.Message}");
            }
        }

        private static HubResult ParseResponse(string text, int statusCode)
        {
            try
            {
                using (var doc = JsonDocument.Parse(text))
                {
                    var root = doc.RootElement;
                    var ok = root.TryGetProperty("ok", out var okEl) && okEl.ValueKind == JsonValueKind.True;
                    if (ok && root.TryGetProperty("result", out var resultEl))
                    {
                        return HubResult.Success(resultEl.Clone());
                    }

                    var error = root.TryGetProperty("error", out var errEl) ? errEl.GetString() : null;
                    return HubResult.Failure(error ?? $"Hub returned HTTP {statusCode}");
                }
            }
            catch (JsonException)
            {
                return HubResult.Failure($"Hub returned an unparseable response (HTTP {statusCode})");
            }
        }
    }

    internal readonly struct HubResult
    {
        public bool Ok { get; }
        public JsonElement Result { get; }
        public string Error { get; }

        private HubResult(bool ok, JsonElement result, string error)
        {
            Ok = ok;
            Result = result;
            Error = error;
        }

        public static HubResult Success(JsonElement result) => new HubResult(true, result, null);

        public static HubResult Failure(string error) => new HubResult(false, default, error);
    }
}
