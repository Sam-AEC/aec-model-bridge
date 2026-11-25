using System;
using System.Collections.Generic;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace RevitBridge.Bridge;

/// <summary>One approved plan action inside a revit.execute_plan_batch request.</summary>
internal sealed class PlanBatchAction
{
    public PlanBatchAction(int index, string actionId, string tool, JsonElement payload)
    {
        Index = index;
        ActionId = actionId;
        Tool = tool;
        Payload = payload;
    }

    public int Index { get; }
    public string ActionId { get; }
    public string Tool { get; }
    public JsonElement Payload { get; }
}

/// <summary>A parsed revit.execute_plan_batch request.</summary>
internal sealed class PlanBatchRequest
{
    public PlanBatchRequest(string planId, string title, List<PlanBatchAction> actions)
    {
        PlanId = planId;
        Title = title;
        Actions = actions;
    }

    public string PlanId { get; }
    public string Title { get; }
    public List<PlanBatchAction> Actions { get; }
}

/// <summary>
/// Request parsing and checks for revit.execute_plan_batch (#294). No Revit types here, so
/// packages/revit-bridge-addin-tests can cover it. The command runs the write actions of one approved
/// plan inside one TransactionGroup in one ExternalEvent turn, so the plan is one undo step. Only plain
/// model writes on the allowlist below may be members; the whole request is refused before anything
/// runs when one member is not allowed. The MCP server claims every action before it sends the request.
/// </summary>
internal static class PlanBatch
{
    public const string CommandName = "revit.execute_plan_batch";
    public const int MaxActions = 50;
    /// <summary>When this much time has passed, the actions still waiting are not run and the group is rolled back.</summary>
    public const int TimeBudgetMs = 30000;
    public const string GroupPrefix = "AEC Model Bridge: ";
    private const int MaxTitleLength = 80;

    // Plain model writes: each opens one BridgeTransaction and nothing else (no files, no views, no
    // selection, no Python, no document switch). Keep this list equal to PLAN_BATCH_COMMANDS in
    // packages/mcp-server-revit/src/revit_mcp_server/providers/revit.py.
    private static readonly HashSet<string> _batchable = new(StringComparer.Ordinal)
    {
        "revit.set_parameter_value",
        "revit.move_element",
        "revit.rotate_element",
    };

    private static readonly Regex PlanIdPattern = new("^[A-Za-z0-9_-]{1,64}$", RegexOptions.CultureInvariant);
    private static readonly Regex ActionIdPattern = new("^[A-Za-z0-9_-]{1,64}$", RegexOptions.CultureInvariant);

    public static IEnumerable<string> BatchableCommands => _batchable;

    /// <summary>True only for a command on the plan-batch allowlist.</summary>
    public static bool IsBatchable(string? tool)
    {
        return !string.IsNullOrEmpty(tool) && _batchable.Contains(tool!);
    }

    /// <summary>
    /// Reads {"plan_id": "...", "title": "...", "actions": [{"action_id": "...", "tool": "...", "payload": {...}}]}.
    /// Throws ArgumentException with a plain message when the shape is wrong, there are no actions or more
    /// than <see cref="MaxActions"/>, or a member is not on the allowlist. <paramref name="isRegistered"/>
    /// must say whether the add-in has a handler for a command.
    /// </summary>
    public static PlanBatchRequest Parse(JsonElement payload, Func<string, bool> isRegistered)
    {
        if (isRegistered == null) throw new ArgumentNullException(nameof(isRegistered));
        if (payload.ValueKind != JsonValueKind.Object)
            throw new ArgumentException("revit.execute_plan_batch needs an object with plan_id, title and actions.");

        if (!payload.TryGetProperty("plan_id", out var planProp)
            || planProp.ValueKind != JsonValueKind.String
            || !PlanIdPattern.IsMatch(planProp.GetString() ?? ""))
        {
            throw new ArgumentException("revit.execute_plan_batch needs a 'plan_id' of letters, digits, '_' or '-'.");
        }
        var planId = planProp.GetString()!;

        var title = "";
        if (payload.TryGetProperty("title", out var titleProp) && titleProp.ValueKind != JsonValueKind.Null)
        {
            if (titleProp.ValueKind != JsonValueKind.String)
                throw new ArgumentException("revit.execute_plan_batch 'title' must be text.");
            title = titleProp.GetString() ?? "";
        }

        if (!payload.TryGetProperty("actions", out var actions) || actions.ValueKind != JsonValueKind.Array)
            throw new ArgumentException("revit.execute_plan_batch needs an 'actions' array of {\"action_id\", \"tool\", \"payload\"} objects.");

        var count = actions.GetArrayLength();
        if (count == 0)
            throw new ArgumentException("revit.execute_plan_batch needs at least one action.");
        if (count > MaxActions)
            throw new ArgumentException($"revit.execute_plan_batch takes at most {MaxActions} actions; this plan has {count}.");

        var list = new List<PlanBatchAction>(count);
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var index = 0;
        foreach (var item in actions.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object)
                throw new ArgumentException($"revit.execute_plan_batch action {index} is not an object.");

            if (!item.TryGetProperty("action_id", out var idProp)
                || idProp.ValueKind != JsonValueKind.String
                || !ActionIdPattern.IsMatch(idProp.GetString() ?? ""))
            {
                throw new ArgumentException($"revit.execute_plan_batch action {index} needs an 'action_id' of letters, digits, '_' or '-'.");
            }
            var actionId = idProp.GetString()!;
            if (!seen.Add(actionId))
                throw new ArgumentException($"revit.execute_plan_batch action {index} repeats action_id '{actionId}'.");

            if (!item.TryGetProperty("tool", out var toolProp)
                || toolProp.ValueKind != JsonValueKind.String
                || string.IsNullOrWhiteSpace(toolProp.GetString()))
            {
                throw new ArgumentException($"revit.execute_plan_batch action {index} needs a 'tool' name.");
            }
            var tool = toolProp.GetString()!;
            if (!IsBatchable(tool))
                throw new ArgumentException($"revit.execute_plan_batch action {index} ({tool}) is not a plain model write that can run in a plan batch. Run this plan one action at a time.");
            if (!isRegistered(tool))
                throw new ArgumentException($"revit.execute_plan_batch action {index} ({tool}) is not a command this add-in has.");

            if (!item.TryGetProperty("payload", out var memberPayload) || memberPayload.ValueKind != JsonValueKind.Object)
                throw new ArgumentException($"revit.execute_plan_batch action {index} ({tool}) needs a 'payload' object.");

            list.Add(new PlanBatchAction(index, actionId, tool, memberPayload));
            index++;
        }

        return new PlanBatchRequest(planId, title, list);
    }

    /// <summary>
    /// The undo-step name: "AEC Model Bridge: &lt;plan title&gt; (&lt;short id&gt;)". The short id is the
    /// first 8 characters of the plan id after a "plan_" prefix. Line breaks and control characters in
    /// the title become spaces and the title is cut to 80 characters.
    /// </summary>
    public static string GroupName(string? title, string planId)
    {
        var id = planId ?? "";
        if (id.StartsWith("plan_", StringComparison.Ordinal)) id = id.Substring(5);
        if (id.Length > 8) id = id.Substring(0, 8);

        var clean = new StringBuilder();
        foreach (var ch in title ?? "")
        {
            clean.Append(char.IsControl(ch) ? ' ' : ch);
        }
        var text = Regex.Replace(clean.ToString(), "\\s+", " ").Trim();
        if (text.Length > MaxTitleLength) text = text.Substring(0, MaxTitleLength - 3).TrimEnd() + "...";
        if (text.Length == 0) text = "plan";
        return $"{GroupPrefix}{text} ({id})";
    }

    /// <summary>
    /// True when a handler's serialized result reports a failure on its own: success false, ok false,
    /// or status error, failed or failure. Mirrors result_failed in the MCP server's dispatch.py.
    /// </summary>
    public static bool IsExplicitFailure(string? resultJson)
    {
        if (string.IsNullOrEmpty(resultJson)) return false;
        try
        {
            using var doc = JsonDocument.Parse(resultJson!);
            var root = doc.RootElement;
            if (root.ValueKind != JsonValueKind.Object) return false;
            if (root.TryGetProperty("success", out var success) && success.ValueKind == JsonValueKind.False) return true;
            if (root.TryGetProperty("ok", out var ok) && ok.ValueKind == JsonValueKind.False) return true;
            if (root.TryGetProperty("status", out var status) && status.ValueKind == JsonValueKind.String)
            {
                var value = status.GetString();
                return value == "error" || value == "failed" || value == "failure";
            }
            return false;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    /// <summary>The failure text from a handler's serialized result (error, then message), or a default.</summary>
    public static string FailureText(string? resultJson)
    {
        const string fallback = "The command reported a failure.";
        if (string.IsNullOrEmpty(resultJson)) return fallback;
        try
        {
            using var doc = JsonDocument.Parse(resultJson!);
            var root = doc.RootElement;
            if (root.ValueKind != JsonValueKind.Object) return fallback;
            foreach (var key in new[] { "error", "message" })
            {
                if (root.TryGetProperty(key, out var prop))
                {
                    if (prop.ValueKind == JsonValueKind.String && !string.IsNullOrEmpty(prop.GetString())) return prop.GetString()!;
                    if (prop.ValueKind == JsonValueKind.Object && prop.TryGetProperty("message", out var inner)
                        && inner.ValueKind == JsonValueKind.String && !string.IsNullOrEmpty(inner.GetString()))
                        return inner.GetString()!;
                }
            }
            return fallback;
        }
        catch (JsonException)
        {
            return fallback;
        }
    }
}
