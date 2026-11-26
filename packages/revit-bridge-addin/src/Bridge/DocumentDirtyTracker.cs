using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Events;

namespace RevitBridge.Bridge
{
    public static class DocumentDirtyTracker
    {
        private static readonly HashSet<string> _dirtyUniqueIds = new();
        private static readonly object _lock = new();

        // Per-document change journal for incremental snapshots (issue 290). Each document has an
        // epoch (a random id) and a sequence number that grows with every DocumentChanged event.
        // A snapshot records the epoch and the sequence number at its start; a later incremental
        // snapshot re-reads the elements changed after that number. The epoch is replaced when the
        // document is opened, closed, reloaded, synchronised with central or saved under a new name,
        // and a new add-in process starts with new epochs, so a base taken before any of those can
        // never be used for an incremental capture.
        private sealed class Journal
        {
            public string Epoch = Guid.NewGuid().ToString("N");
            public long Seq;
            public readonly Dictionary<string, long> ChangedAt = new(StringComparer.Ordinal);
        }

        private static readonly Dictionary<string, Journal> _journals = new(StringComparer.OrdinalIgnoreCase);

        // A journal that records more distinct elements than this starts a new epoch, so memory stays
        // bounded; the next snapshot after that is a full capture.
        private const int JournalMaxEntries = 500000;

        public static void Clear()
        {
            lock (_lock)
            {
                _dirtyUniqueIds.Clear();
            }
        }

        public static List<string> GetDirtyUniqueIds()
        {
            lock (_lock)
            {
                return _dirtyUniqueIds.ToList();
            }
        }

        public static void Add(string uniqueId)
        {
            lock (_lock)
            {
                _dirtyUniqueIds.Add(uniqueId);
            }
        }

        /// <summary>Key of a document in the journal: its path, or its title while it is unsaved.</summary>
        public static string DocumentKey(Document doc)
        {
            string? path = null;
            try { path = doc.PathName; } catch { }
            return string.IsNullOrEmpty(path) ? "title:" + doc.Title : "path:" + path;
        }

        /// <summary>The document's journal epoch and current sequence number (a journal is created if missing).</summary>
        public static void GetJournalState(Document doc, out string epoch, out long seq)
        {
            var key = DocumentKey(doc);
            lock (_lock)
            {
                var journal = GetOrCreate(key);
                epoch = journal.Epoch;
                seq = journal.Seq;
            }
        }

        /// <summary>
        /// UniqueIds changed (added or modified) after <paramref name="sinceSeq"/> in the journal with
        /// <paramref name="epoch"/>. Returns null when the document's journal has a different epoch:
        /// the change history since the base is not known, so the caller must extract everything.
        /// </summary>
        public static HashSet<string>? GetChangedSince(Document doc, string epoch, long sinceSeq)
        {
            var key = DocumentKey(doc);
            lock (_lock)
            {
                if (!_journals.TryGetValue(key, out var journal)) return null;
                if (!string.Equals(journal.Epoch, epoch, StringComparison.Ordinal)) return null;
                if (sinceSeq < 0 || sinceSeq > journal.Seq) return null;
                var result = new HashSet<string>(StringComparer.Ordinal);
                foreach (var pair in journal.ChangedAt)
                {
                    if (pair.Value > sinceSeq) result.Add(pair.Key);
                }
                return result;
            }
        }

        /// <summary>Forget the document's change history; the next snapshot of it starts a new epoch.</summary>
        public static void ResetDocument(Document? doc)
        {
            if (doc == null) return;
            string key;
            try { key = DocumentKey(doc); } catch { return; }
            lock (_lock)
            {
                _journals.Remove(key);
            }
        }

        private static Journal GetOrCreate(string key)
        {
            if (!_journals.TryGetValue(key, out var journal))
            {
                journal = new Journal();
                _journals[key] = journal;
            }
            return journal;
        }

        public static void HandleDocumentChanged(object sender, DocumentChangedEventArgs e)
        {
            var doc = e.GetDocument();
            if (doc == null) return;

            string? key = null;
            try { key = DocumentKey(doc); } catch { }

            lock (_lock)
            {
                Journal? journal = key == null ? null : GetOrCreate(key);
                if (journal != null) journal.Seq++;
                long seq = journal?.Seq ?? 0;

                foreach (var id in e.GetAddedElementIds())
                {
                    var elem = doc.GetElement(id);
                    if (elem != null && !string.IsNullOrEmpty(elem.UniqueId))
                    {
                        _dirtyUniqueIds.Add(elem.UniqueId);
                        if (journal != null) journal.ChangedAt[elem.UniqueId] = seq;
                    }
                }

                foreach (var id in e.GetModifiedElementIds())
                {
                    var elem = doc.GetElement(id);
                    if (elem != null && !string.IsNullOrEmpty(elem.UniqueId))
                    {
                        _dirtyUniqueIds.Add(elem.UniqueId);
                        if (journal != null) journal.ChangedAt[elem.UniqueId] = seq;
                    }
                }

                if (journal != null && key != null && journal.ChangedAt.Count > JournalMaxEntries)
                {
                    _journals[key] = new Journal();
                }

                foreach (var id in e.GetDeletedElementIds())
                {
                    // Deletions need no journal entry: an incremental snapshot lists every UniqueId in
                    // scope, and the server drops base records that are no longer in that list.
                    _dirtyUniqueIds.Add($"deleted:{id.Value}");
                }
            }
        }
    }
}
