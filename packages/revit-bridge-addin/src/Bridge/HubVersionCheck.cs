using System;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace RevitBridge.Bridge;

/// <summary>
/// Compares the version of the running panel hub with this add-in's version. An old hub can keep
/// serving after Revit restarts with a newer add-in; this turns that into a message and a failing
/// Setup check. It never stops a process. No Revit types, so the tests link this file.
/// </summary>
public static class HubVersionCheck
{
    public const string CheckId = "hub_version";

    private static readonly Regex Core = new Regex(@"^\s*v?(\d+)\.(\d+)\.(\d+)", RegexOptions.CultureInvariant);

    /// <summary>True when the hub version is missing or its major.minor.patch differs from the add-in's.</summary>
    public static bool IsMismatch(string? hubVersion, string addinVersion)
    {
        var hub = Core.Match(hubVersion ?? "");
        if (!hub.Success) return true;
        var addin = Core.Match(addinVersion ?? "");
        if (!addin.Success) return false;
        for (var i = 1; i <= 3; i++)
        {
            if (hub.Groups[i].Value.TrimStart('0') != addin.Groups[i].Value.TrimStart('0')) return true;
        }
        return false;
    }

    public static string Detail(string? hubVersion, string addinVersion)
    {
        var hub = string.IsNullOrWhiteSpace(hubVersion) ? "an older version that does not report one" : hubVersion!.Trim();
        return $"The panel hub running on this machine is {hub}, but the add-in is {addinVersion}. The panel may show old behaviour.";
    }

    public const string NextStep =
        "Close the hub window or end the 'aec-model-bridge-panel-server' (python) process, then restart Revit or press Refresh so the add-in starts a matching hub.";

    /// <summary>
    /// Reads hub_version from a /diagnostics answer. When it differs from the add-in's version, returns a copy
    /// of the answer with a failing hub_version check appended and ok set to false; otherwise the input.
    /// </summary>
    public static JsonElement Apply(JsonElement diagnostics, string addinVersion)
    {
        if (diagnostics.ValueKind != JsonValueKind.Object) return diagnostics;
        string? hubVersion = null;
        if (diagnostics.TryGetProperty("hub_version", out var value) && value.ValueKind == JsonValueKind.String)
            hubVersion = value.GetString();
        if (!IsMismatch(hubVersion, addinVersion)) return diagnostics;

        var node = JsonNode.Parse(diagnostics.GetRawText()) as JsonObject;
        if (node == null || node["checks"] is not JsonArray checks) return diagnostics;
        checks.Add(new JsonObject
        {
            ["id"] = CheckId,
            ["ok"] = false,
            ["detail"] = Detail(hubVersion, addinVersion),
            ["next_step"] = NextStep
        });
        node["ok"] = false;
        using var parsed = JsonDocument.Parse(node.ToJsonString());
        return parsed.RootElement.Clone();
    }
}
