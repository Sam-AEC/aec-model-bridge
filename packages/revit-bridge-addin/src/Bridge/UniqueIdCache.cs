using System;
using System.Collections.Generic;

namespace RevitBridge.Bridge;

/// <summary>
/// UniqueId to ElementId cache, kept per open document (#292). No Revit types here, so
/// packages/revit-bridge-addin-tests can cover it; <see cref="ElementLookup"/> wires it to Revit.
/// Entries are dropped when the element is deleted (DocumentChanged), when the document closes,
/// and when the active document changes. A cached id is only a hint: ElementLookup checks the
/// element's UniqueId again before using it, so a missed invalidation cannot return a wrong element.
/// </summary>
internal sealed class UniqueIdCache
{
    private sealed class DocumentEntries
    {
        public readonly Dictionary<string, long> ByUniqueId = new(StringComparer.Ordinal);
        public readonly Dictionary<long, string> ByElementId = new();
    }

    private readonly object _sync = new();
    private readonly Dictionary<string, DocumentEntries> _documents = new(StringComparer.Ordinal);
    private string? _activeDocument;

    public UniqueIdCache(int maxEntriesPerDocument = 200000)
    {
        if (maxEntriesPerDocument < 1) throw new ArgumentOutOfRangeException(nameof(maxEntriesPerDocument));
        MaxEntriesPerDocument = maxEntriesPerDocument;
    }

    /// <summary>A document that reaches this many entries starts again empty (bounded memory).</summary>
    public int MaxEntriesPerDocument { get; }

    public bool TryGet(string documentKey, string uniqueId, out long elementId)
    {
        lock (_sync)
        {
            if (_documents.TryGetValue(documentKey, out var entries)
                && entries.ByUniqueId.TryGetValue(uniqueId, out elementId))
            {
                return true;
            }
        }

        elementId = 0;
        return false;
    }

    public void Put(string documentKey, string uniqueId, long elementId)
    {
        if (string.IsNullOrEmpty(documentKey) || string.IsNullOrEmpty(uniqueId)) return;
        lock (_sync)
        {
            if (!_documents.TryGetValue(documentKey, out var entries))
            {
                entries = new DocumentEntries();
                _documents[documentKey] = entries;
            }
            else if (entries.ByUniqueId.Count >= MaxEntriesPerDocument && !entries.ByUniqueId.ContainsKey(uniqueId))
            {
                entries.ByUniqueId.Clear();
                entries.ByElementId.Clear();
            }

            if (entries.ByUniqueId.TryGetValue(uniqueId, out var oldId))
                entries.ByElementId.Remove(oldId);
            if (entries.ByElementId.TryGetValue(elementId, out var oldUid))
                entries.ByUniqueId.Remove(oldUid);

            entries.ByUniqueId[uniqueId] = elementId;
            entries.ByElementId[elementId] = uniqueId;
        }
    }

    /// <summary>Drops one UniqueId, for example after the cached id no longer matched.</summary>
    public void Forget(string documentKey, string uniqueId)
    {
        lock (_sync)
        {
            if (_documents.TryGetValue(documentKey, out var entries)
                && entries.ByUniqueId.TryGetValue(uniqueId, out var id))
            {
                entries.ByUniqueId.Remove(uniqueId);
                entries.ByElementId.Remove(id);
            }
        }
    }

    /// <summary>Drops the entries of deleted elements (DocumentChanged gives ElementIds only).</summary>
    public void RemoveElementIds(string documentKey, IEnumerable<long> deletedIds)
    {
        lock (_sync)
        {
            if (!_documents.TryGetValue(documentKey, out var entries)) return;
            foreach (var id in deletedIds)
            {
                if (entries.ByElementId.TryGetValue(id, out var uid))
                {
                    entries.ByElementId.Remove(id);
                    entries.ByUniqueId.Remove(uid);
                }
            }
        }
    }

    /// <summary>Drops everything cached for one document (document closing).</summary>
    public void ClearDocument(string documentKey)
    {
        lock (_sync)
        {
            _documents.Remove(documentKey);
        }
    }

    /// <summary>
    /// Records the active document. When it differs from the last one, the whole cache is cleared:
    /// a switch is rare, and starting empty is cheaper than reasoning about which entries still hold.
    /// </summary>
    public void SetActiveDocument(string? documentKey)
    {
        lock (_sync)
        {
            if (string.Equals(_activeDocument, documentKey, StringComparison.Ordinal)) return;
            _activeDocument = documentKey;
            _documents.Clear();
        }
    }

    public void Clear()
    {
        lock (_sync)
        {
            _documents.Clear();
        }
    }

    public int Count(string documentKey)
    {
        lock (_sync)
        {
            return _documents.TryGetValue(documentKey, out var entries) ? entries.ByUniqueId.Count : 0;
        }
    }
}
