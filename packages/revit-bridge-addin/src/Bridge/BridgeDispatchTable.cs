using System;
using System.Collections.Generic;
#if NET8_0_OR_GREATER
using System.Collections.Frozen;
#endif

namespace RevitBridge.Bridge;

/// <summary>
/// Builds the command name to handler table once at start (#291). No Revit types here, so
/// packages/revit-bridge-addin-tests can cover it. A duplicate or blank name throws, so a second
/// [BridgeCommand] with the same name can no longer silently replace the first handler.
/// net8 and net10 get a FrozenDictionary (faster lookups, read-only); net48 a Dictionary behind
/// IReadOnlyDictionary.
/// </summary>
internal static class BridgeDispatchTable
{
    public static IReadOnlyDictionary<string, THandler> Build<THandler>(IEnumerable<KeyValuePair<string, THandler>> entries)
    {
        if (entries == null) throw new ArgumentNullException(nameof(entries));

        var table = new Dictionary<string, THandler>(StringComparer.Ordinal);
        foreach (var entry in entries)
        {
            if (string.IsNullOrWhiteSpace(entry.Key))
                throw new InvalidOperationException("A bridge command has a blank name.");
            if (table.ContainsKey(entry.Key))
                throw new InvalidOperationException($"Bridge command '{entry.Key}' is declared more than once. Each [BridgeCommand] name must be unique.");
            table.Add(entry.Key, entry.Value);
        }

#if NET8_0_OR_GREATER
        return table.ToFrozenDictionary(StringComparer.Ordinal);
#else
        return table;
#endif
    }
}
