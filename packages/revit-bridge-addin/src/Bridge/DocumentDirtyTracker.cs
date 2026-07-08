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

        public static void HandleDocumentChanged(object sender, DocumentChangedEventArgs e)
        {
            var doc = e.GetDocument();
            if (doc == null) return;

            lock (_lock)
            {
                foreach (var id in e.GetAddedElementIds())
                {
                    var elem = doc.GetElement(id);
                    if (elem != null && !string.IsNullOrEmpty(elem.UniqueId))
                    {
                        _dirtyUniqueIds.Add(elem.UniqueId);
                    }
                }

                foreach (var id in e.GetModifiedElementIds())
                {
                    var elem = doc.GetElement(id);
                    if (elem != null && !string.IsNullOrEmpty(elem.UniqueId))
                    {
                        _dirtyUniqueIds.Add(elem.UniqueId);
                    }
                }

                foreach (var id in e.GetDeletedElementIds())
                {
                    _dirtyUniqueIds.Add($"deleted:{id.Value}");
                }
            }
        }
    }
}
