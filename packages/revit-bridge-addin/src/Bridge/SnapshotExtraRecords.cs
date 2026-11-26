using System;
using System.Collections.Generic;
using System.Linq;

namespace RevitBridge.Bridge;

/// <summary>
/// Builds the optional snapshot blocks selected by the "include" option (issue 146): "types",
/// "cad" and "rooms". Plain values only, no Revit types, so the rules can be tested without Revit.
/// The Revit side reads the elements and feeds this class. A snapshot without "include" carries
/// none of these keys.
/// </summary>
internal static class SnapshotExtraRecords
{
    public const string TypesBlock = "types";
    public const string CadBlock = "cad";
    public const string RoomsBlock = "rooms";

    private static readonly string[] KnownBlocks = { TypesBlock, CadBlock, RoomsBlock };

    /// <summary>Which optional blocks a snapshot call asked for.</summary>
    public sealed class Selection
    {
        public Selection(bool types, bool cad, bool rooms)
        {
            Types = types;
            Cad = cad;
            Rooms = rooms;
        }

        public bool Types { get; }
        public bool Cad { get; }
        public bool Rooms { get; }

        public bool Any => Types || Cad || Rooms;

        /// <summary>Block names in a fixed order; written to counts.include so a later read knows what was captured.</summary>
        public List<string> Names()
        {
            var names = new List<string>();
            if (Types) names.Add(TypesBlock);
            if (Cad) names.Add(CadBlock);
            if (Rooms) names.Add(RoomsBlock);
            return names;
        }
    }

    /// <summary>
    /// Reads the "include" names. Case and surrounding spaces are ignored, repeats are dropped, and a
    /// name that is not a known block is refused (the server refuses it first; this guards direct calls).
    /// </summary>
    public static Selection Parse(IEnumerable<string?>? names)
    {
        bool types = false, cad = false, rooms = false;
        foreach (var raw in names ?? Enumerable.Empty<string?>())
        {
            var name = (raw ?? string.Empty).Trim().ToLowerInvariant();
            switch (name)
            {
                case TypesBlock: types = true; break;
                case CadBlock: cad = true; break;
                case RoomsBlock: rooms = true; break;
                default:
                    throw new ArgumentException(
                        $"include has an unknown block '{raw}'. Known blocks: {string.Join(", ", KnownBlocks)}");
            }
        }
        return new Selection(types, cad, rooms);
    }

    /// <summary>One "types" entry. uid is the type's ElementId as text, the same value element records carry in type_uid.</summary>
    public static Dictionary<string, object?> BuildType(
        string uid, string? category, string? family, string? typeName, string familySource, int instanceCount)
        => new()
        {
            ["uid"] = uid,
            ["category"] = category ?? "None",
            ["family"] = family ?? string.Empty,
            ["type_name"] = typeName ?? string.Empty,
            ["family_source"] = NormalizeFamilySource(familySource),
            ["params"] = new Dictionary<string, object>(),
            ["instance_count"] = Math.Max(0, instanceCount),
        };

    /// <summary>system, loadable or inplace; anything else is read as loadable.</summary>
    public static string NormalizeFamilySource(string? source)
    {
        var s = (source ?? string.Empty).Trim().ToLowerInvariant();
        return s == "system" || s == "inplace" ? s : "loadable";
    }

    /// <summary>One "cad" entry: element_id, name, is_link, view_specific.</summary>
    public static Dictionary<string, object?> BuildCad(long elementId, string? name, bool isLink, bool viewSpecific)
        => new()
        {
            ["element_id"] = elementId,
            ["name"] = string.IsNullOrWhiteSpace(name) ? "(unnamed CAD)" : name,
            ["is_link"] = isLink,
            ["view_specific"] = viewSpecific,
        };

    /// <summary>
    /// The value of a door's "From Room" or "To Room" parameter: the room's UniqueId, or an empty string
    /// when the door has no room on that side. The key is written for every door, so an empty value means
    /// "no room" and a missing key means "not captured".
    /// </summary>
    public static Dictionary<string, object> BuildRoomRefParam(string? roomUniqueId)
        => new()
        {
            ["v"] = roomUniqueId ?? string.Empty,
            ["storage"] = "String",
            ["instance"] = true,
            ["readonly"] = true,
        };
}
