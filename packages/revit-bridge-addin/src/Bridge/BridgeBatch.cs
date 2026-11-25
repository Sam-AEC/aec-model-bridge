using System;
using System.Collections.Generic;
using System.Text.Json;

namespace RevitBridge.Bridge;

/// <summary>One command inside a revit.batch request.</summary>
internal sealed class BridgeBatchMember
{
    public BridgeBatchMember(int index, string tool, JsonElement payload)
    {
        Index = index;
        Tool = tool;
        Payload = payload;
    }

    public int Index { get; }
    public string Tool { get; }
    public JsonElement Payload { get; }
}

/// <summary>
/// Request parsing and checks for the revit.batch command (#277). No Revit types here, so
/// packages/revit-bridge-addin-tests can cover it. The whole batch is refused before any member
/// runs when one member is not allowed, so a refused batch never runs half of its commands.
/// </summary>
internal static class BridgeBatch
{
    public const string CommandName = "revit.batch";
    public const int MaxCommands = 25;
    /// <summary>Members still waiting when this much time has passed in one batch are not run.</summary>
    public const int TimeBudgetMs = 20000;

    /// <summary>
    /// Commands declared IsMutating = false that still have side effects: they write files, open a
    /// transaction, change the selection or view, or reset the dirty tracker. A batch never runs them.
    /// Every command named revit.export_* is refused as well.
    /// </summary>
    private static readonly HashSet<string> _sideEffectCommands = new(StringComparer.OrdinalIgnoreCase)
    {
        "revit.extract_snapshot",
        "revit.get_snapshot_delta",
        "revit.select_by_unique_ids",
        "revit.preview_elements",
        "revit.clear_preview",
    };

    public static IEnumerable<string> SideEffectCommands => _sideEffectCommands;

    /// <summary>True for a command that a batch refuses whatever its attribute says.</summary>
    public static bool HasSideEffects(string tool)
    {
        if (string.IsNullOrEmpty(tool)) return true;
        return tool.StartsWith("revit.export_", StringComparison.OrdinalIgnoreCase)
            || _sideEffectCommands.Contains(tool);
    }

    private static readonly JsonElement EmptyObject = ParseEmptyObject();

    private static JsonElement ParseEmptyObject()
    {
        using var doc = JsonDocument.Parse("{}");
        return doc.RootElement.Clone();
    }

    /// <summary>
    /// Reads {"commands": [{"tool": "...", "payload": {...}}, ...]}. Throws ArgumentException with a
    /// plain message when the shape is wrong, the batch is empty or over <see cref="MaxCommands"/>,
    /// a member is revit.batch itself, a member has side effects (<see cref="HasSideEffects"/>), or <paramref name="isReadOnly"/> says a member is not a
    /// read-only command (unknown commands included).
    /// </summary>
    public static List<BridgeBatchMember> Parse(JsonElement payload, Func<string, bool> isReadOnly)
    {
        if (isReadOnly == null) throw new ArgumentNullException(nameof(isReadOnly));
        if (payload.ValueKind != JsonValueKind.Object
            || !payload.TryGetProperty("commands", out var commands)
            || commands.ValueKind != JsonValueKind.Array)
        {
            throw new ArgumentException("revit.batch needs a 'commands' array of {\"tool\": ..., \"payload\": {...}} objects.");
        }

        var count = commands.GetArrayLength();
        if (count == 0)
            throw new ArgumentException("revit.batch needs at least one command.");
        if (count > MaxCommands)
            throw new ArgumentException($"revit.batch takes at most {MaxCommands} commands; this request has {count}. Split it into smaller batches.");

        var members = new List<BridgeBatchMember>(count);
        var index = 0;
        foreach (var item in commands.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object
                || !item.TryGetProperty("tool", out var toolProp)
                || toolProp.ValueKind != JsonValueKind.String
                || string.IsNullOrWhiteSpace(toolProp.GetString()))
            {
                throw new ArgumentException($"revit.batch command {index} needs a 'tool' name.");
            }

            var tool = toolProp.GetString()!;
            if (string.Equals(tool, CommandName, StringComparison.OrdinalIgnoreCase))
                throw new ArgumentException($"revit.batch command {index} is revit.batch; batches cannot be nested.");
            if (HasSideEffects(tool))
                throw new ArgumentException($"revit.batch command {index} ({tool}) writes files or changes the selection or view, so it cannot run in a batch. Send it on its own.");
            if (!isReadOnly(tool))
                throw new ArgumentException($"revit.batch command {index} ({tool}) is not a read-only command. A batch runs reads only; model changes go through a plan.");

            JsonElement memberPayload;
            if (!item.TryGetProperty("payload", out memberPayload) || memberPayload.ValueKind == JsonValueKind.Null)
            {
                memberPayload = EmptyObject;
            }
            else if (memberPayload.ValueKind != JsonValueKind.Object)
            {
                throw new ArgumentException($"revit.batch command {index} ({tool}) has a payload that is not an object.");
            }

            members.Add(new BridgeBatchMember(index, tool, memberPayload));
            index++;
        }

        return members;
    }
}
