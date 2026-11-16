using System;
using System.Collections.Generic;
using System.Linq;

namespace RevitBridge.Bridge;

/// <summary>
/// Builds the top-level "views" and "sheets" records of a snapshot from plain values (issue 142).
/// No Revit types here, so the rules can be tested without Revit. The Revit side only reads the
/// elements and feeds this class.
/// </summary>
internal static class SnapshotViewRecords
{
    // View types Revit never places on a sheet, plus the sheet itself. Mirrors the audit module.
    private static readonly HashSet<string> SkippedViewTypes = new(StringComparer.OrdinalIgnoreCase)
    {
        "Undefined", "DrawingSheet", "ProjectBrowser", "SystemBrowser", "Internal"
    };

    /// <summary>False for sheets, browsers and internal or system views.</summary>
    public static bool IsCapturableViewType(string? viewType)
        => !string.IsNullOrWhiteSpace(viewType) && !SkippedViewTypes.Contains(viewType!.Trim());

    /// <summary>Which views sit on which sheets. Duplicate links are ignored; order is kept.</summary>
    public sealed class PlacementMap
    {
        private readonly Dictionary<string, List<string>> _viewsBySheet = new(StringComparer.Ordinal);
        private readonly Dictionary<string, string> _firstSheetByView = new(StringComparer.Ordinal);

        public int LinkCount { get; private set; }

        public void Add(string? sheetUid, string? viewUid)
        {
            if (string.IsNullOrEmpty(sheetUid) || string.IsNullOrEmpty(viewUid)) return;
            if (!_viewsBySheet.TryGetValue(sheetUid!, out var list))
                _viewsBySheet[sheetUid!] = list = new List<string>();
            if (list.Contains(viewUid!)) return;
            list.Add(viewUid!);
            LinkCount++;
            if (!_firstSheetByView.ContainsKey(viewUid!)) _firstSheetByView[viewUid!] = sheetUid!;
        }

        public IReadOnlyList<string> ViewUidsOn(string sheetUid)
            => _viewsBySheet.TryGetValue(sheetUid, out var list) ? list : Array.Empty<string>();

        /// <summary>The first sheet a view was placed on, or null when it is on no sheet.</summary>
        public string? SheetOf(string viewUid)
            => _firstSheetByView.TryGetValue(viewUid, out var sheet) ? sheet : null;
    }

    /// <summary>One "views" entry: uid, name, view_type, is_template, sheet_uid, discipline.</summary>
    public static Dictionary<string, object?> BuildView(
        string uid, string? name, string viewType, bool isTemplate, string? sheetUid, string? discipline)
        => new()
        {
            ["uid"] = uid,
            ["name"] = name ?? string.Empty,
            ["view_type"] = viewType,
            ["is_template"] = isTemplate,
            ["sheet_uid"] = isTemplate ? null : sheetUid,
            ["discipline"] = discipline ?? string.Empty,
        };

    /// <summary>One "sheets" entry: uid, number, name, view_uids, params.</summary>
    public static Dictionary<string, object?> BuildSheet(
        string uid, string? number, string? name, IEnumerable<string> viewUids, IDictionary<string, object>? parameters)
        => new()
        {
            ["uid"] = uid,
            ["number"] = number ?? string.Empty,
            ["name"] = name ?? string.Empty,
            ["view_uids"] = viewUids.ToList(),
            ["params"] = parameters ?? new Dictionary<string, object>(),
        };
}
