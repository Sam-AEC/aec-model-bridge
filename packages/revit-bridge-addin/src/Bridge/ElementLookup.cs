using System;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Events;
using Autodesk.Revit.UI.Events;
using Serilog;

namespace RevitBridge.Bridge;

/// <summary>
/// Resolves UniqueIds through <see cref="UniqueIdCache"/> (#292). Revit API only: call it on the
/// Revit thread (inside a bridge command or a Revit event handler).
/// UNVERIFIED in live Revit: the speed-up over Document.GetElement(string) is not measured yet.
/// </summary>
internal static class ElementLookup
{
    internal static readonly UniqueIdCache Cache = new();

    /// <summary>A key for one open document: its path, or its title while it has never been saved.</summary>
    internal static string DocumentKey(Document doc)
    {
        var path = doc.PathName;
        return string.IsNullOrEmpty(path) ? "title:" + doc.Title : "path:" + path;
    }

    /// <summary>
    /// Same result as doc.GetElement(uniqueId). A cached ElementId is used only when the element it
    /// names still has this UniqueId; otherwise the entry is dropped and Revit is asked again.
    /// </summary>
    internal static Element? ByUniqueId(Document doc, string? uniqueId)
    {
        if (string.IsNullOrEmpty(uniqueId))
        {
            // Keep the uncached behaviour for null or empty input.
            return doc.GetElement(uniqueId);
        }

        var key = DocumentKey(doc);
        if (Cache.TryGet(key, uniqueId!, out var cached))
        {
            Element? hit = null;
            try { hit = doc.GetElement(new ElementId(cached)); } catch { hit = null; }
            if (hit != null && string.Equals(hit.UniqueId, uniqueId, StringComparison.Ordinal))
                return hit;
            Cache.Forget(key, uniqueId!);
        }

        var element = doc.GetElement(uniqueId);
        if (element != null)
            Cache.Put(key, uniqueId!, element.Id.Value);
        return element;
    }

    internal static void OnDocumentChanged(DocumentChangedEventArgs args)
    {
        try
        {
            var doc = args.GetDocument();
            if (doc == null) return;
            var deleted = args.GetDeletedElementIds();
            if (deleted == null || deleted.Count == 0) return;
            Cache.RemoveElementIds(DocumentKey(doc), deleted.Select(id => id.Value));
        }
        catch (Exception ex)
        {
            // Never let the cache break Revit's event; the per-use UniqueId check keeps lookups correct.
            Log.Debug(ex, "UniqueId cache: could not apply deletions; clearing it");
            Cache.Clear();
        }
    }

    internal static void OnDocumentClosing(DocumentClosingEventArgs args)
    {
        try
        {
            var doc = args.Document;
            if (doc != null) Cache.ClearDocument(DocumentKey(doc));
        }
        catch (Exception ex)
        {
            Log.Debug(ex, "UniqueId cache: could not read the closing document; clearing it");
            Cache.Clear();
        }
    }

    internal static void OnViewActivated(ViewActivatedEventArgs args)
    {
        try
        {
            var doc = args.CurrentActiveView?.Document;
            Cache.SetActiveDocument(doc == null ? null : DocumentKey(doc));
        }
        catch (Exception ex)
        {
            Log.Debug(ex, "UniqueId cache: could not read the active document; clearing it");
            Cache.Clear();
        }
    }
}
