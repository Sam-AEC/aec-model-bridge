using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevitBridge.Commands.Advanced.Worksharing
{
    /// <summary>
    /// Worksharing and workset management commands
    /// WorksharingUtils (#16, Score: 273), Workset (#440, Score: 187)
    /// </summary>
    public static class WorksharingCommands
    {
        #region 1. Create Workset

        public static object CreateWorkset(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            string worksetName = payload.GetProperty("name").GetString();

            if (!doc.IsWorkshared)
            {
                throw new Exception("Document is not workshared");
            }

            using (var trans = new Transaction(doc, "Create Workset"))
            {
                trans.Start();

                Workset newWorkset = Workset.Create(doc, worksetName);

                trans.Commit();

                return new
                {
                    success = true,
                    worksetId = newWorkset.Id.IntegerValue,
                    worksetName = newWorkset.Name,
                    kind = newWorkset.Kind.ToString(),
                    isOpen = newWorkset.IsOpen
                };
            }
        }

        #endregion

        #region 2. Rename Workset

        public static object RenameWorkset(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int worksetId = payload.GetProperty("workset_id").GetInt32();
            string newName = payload.GetProperty("new_name").GetString();

            if (!doc.IsWorkshared)
            {
                throw new Exception("Document is not workshared");
            }

            using (var trans = new Transaction(doc, "Rename Workset"))
            {
                trans.Start();

                WorksetTable worksetTable = doc.GetWorksetTable();
                Workset workset = worksetTable.GetWorkset(new WorksetId(worksetId));

                string oldName = workset.Name;
                WorksetTable.RenameWorkset(doc, new WorksetId(worksetId), newName);

                trans.Commit();

                return new
                {
                    success = true,
                    worksetId = worksetId,
                    oldName = oldName,
                    newName = newName
                };
            }
        }

        #endregion

        #region 3. Set Element Workset

        public static object SetElementWorkset(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int elementId = payload.GetProperty("element_id").GetInt32();
            int worksetId = payload.GetProperty("workset_id").GetInt32();

            if (!doc.IsWorkshared)
            {
                throw new Exception("Document is not workshared");
            }

            Element element = doc.GetElement(new ElementId(elementId));
            if (element == null)
            {
                throw new Exception($"Element {elementId} not found");
            }

            using (var trans = new Transaction(doc, "Set Element Workset"))
            {
                trans.Start();

                Parameter worksetParam = element.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM);
                if (worksetParam != null)
                {
                    worksetParam.Set(worksetId);
                }

                trans.Commit();

                return new
                {
                    success = true,
                    elementId = elementId,
                    elementName = element.Name,
                    worksetId = worksetId,
                    worksetName = doc.GetWorksetTable().GetWorkset(new WorksetId(worksetId)).Name
                };
            }
        }

        #endregion

        #region 4. Get Element Workset

        public static object GetElementWorkset(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int elementId = payload.GetProperty("element_id").GetInt32();

            if (!doc.IsWorkshared)
            {
                throw new Exception("Document is not workshared");
            }

            Element element = doc.GetElement(new ElementId(elementId));
            if (element == null)
            {
                throw new Exception($"Element {elementId} not found");
            }

            Parameter worksetParam = element.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM);
            if (worksetParam == null)
            {
                return new { elementId = elementId, workset = "None" };
            }

            WorksetId worksetId = new WorksetId(worksetParam.AsInteger());
            Workset workset = doc.GetWorksetTable().GetWorkset(worksetId);

            return new
            {
                elementId = elementId,
                elementName = element.Name,
                worksetId = worksetId.IntegerValue,
                worksetName = workset.Name,
                isOpen = workset.IsOpen,
                isEditable = workset.IsEditable
            };
        }

        #endregion

        #region 5. Checkout Elements

        public static object CheckoutElements(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            var elementIds = payload.GetProperty("element_ids").EnumerateArray()
                .Select(e => new ElementId(e.GetInt32())).ToList();

            if (!doc.IsWorkshared)
            {
                throw new Exception("Document is not workshared");
            }

            using (var trans = new Transaction(doc, "Checkout Elements"))
            {
                trans.Start();

                int checkedOut = 0;
                var results = new List<object>();

                foreach (var id in elementIds)
                {
                    Element element = doc.GetElement(id);
                    if (element != null)
                    {
                        WorksharingUtils.CheckoutElements(doc, new List<ElementId> { id });
                        checkedOut++;
                        results.Add(new { id = id.IntegerValue, name = element.Name, status = "checked_out" });
                    }
                }

                trans.Commit();

                return new
                {
                    success = true,
                    requestedCount = elementIds.Count,
                    checkedOutCount = checkedOut,
                    elements = results
                };
            }
        }

        #endregion

        #region 6. Get Workset Owner

        public static object GetWorksetOwner(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int worksetId = payload.GetProperty("workset_id").GetInt32();

            if (!doc.IsWorkshared)
            {
                throw new Exception("Document is not workshared");
            }

            WorksetTable worksetTable = doc.GetWorksetTable();
            Workset workset = worksetTable.GetWorkset(new WorksetId(worksetId));

            string owner = WorksharingUtils.GetWorksharingTooltipInfo(doc, new WorksetId(worksetId)).Owner;

            return new
            {
                worksetId = worksetId,
                worksetName = workset.Name,
                owner = owner,
                isOpen = workset.IsOpen,
                isEditable = workset.IsEditable,
                kind = workset.Kind.ToString()
            };
        }

        #endregion

        #region 7. Enable Worksharing

        public static object EnableWorksharing(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            string defaultWorksetName = payload.TryGetProperty("default_workset_name", out var dwn)
                ? dwn.GetString()
                : "Shared Levels and Grids";

            if (doc.IsWorkshared)
            {
                return new { success = false, message = "Document is already workshared" };
            }

            using (var trans = new Transaction(doc, "Enable Worksharing"))
            {
                trans.Start();

                // Enable worksharing
                doc.EnableWorksharing(defaultWorksetName, "Workset1");

                trans.Commit();

                return new
                {
                    success = true,
                    message = "Worksharing enabled",
                    defaultWorkset = defaultWorksetName,
                    isWorkshared = doc.IsWorkshared
                };
            }
        }

        #endregion

        #region 8. Get Central Path

        public static object GetCentralPath(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;

            if (!doc.IsWorkshared)
            {
                throw new Exception("Document is not workshared");
            }

            ModelPath centralPath = doc.GetWorksharingCentralModelPath();
            string centralPathString = ModelPathUtils.ConvertModelPathToUserVisiblePath(centralPath);

            return new
            {
                isWorkshared = doc.IsWorkshared,
                centralPath = centralPathString,
                isDetached = doc.IsDetached,
                isModified = doc.IsModified,
                title = doc.Title
            };
        }

        #endregion

        #region 9. Set Workset Visibility

        public static object SetWorksetVisibility(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int viewId = payload.GetProperty("view_id").GetInt32();
            int worksetId = payload.GetProperty("workset_id").GetInt32();
            bool visible = payload.GetProperty("visible").GetBoolean();

            if (!doc.IsWorkshared)
            {
                throw new Exception("Document is not workshared");
            }

            View view = doc.GetElement(new ElementId(viewId)) as View;
            if (view == null)
            {
                throw new Exception($"View {viewId} not found");
            }

            using (var trans = new Transaction(doc, "Set Workset Visibility"))
            {
                trans.Start();

                WorksetId wsId = new WorksetId(worksetId);
                WorksetVisibility visibility = visible ? WorksetVisibility.Visible : WorksetVisibility.Hidden;
                view.SetWorksetVisibility(wsId, visibility);

                trans.Commit();

                return new
                {
                    success = true,
                    viewId = viewId,
                    viewName = view.Name,
                    worksetId = worksetId,
                    visible = visible
                };
            }
        }

        #endregion

        #region 10. Get Workset Visibility

        public static object GetWorksetVisibility(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int viewId = payload.GetProperty("view_id").GetInt32();
            int worksetId = payload.GetProperty("workset_id").GetInt32();

            if (!doc.IsWorkshared)
            {
                throw new Exception("Document is not workshared");
            }

            View view = doc.GetElement(new ElementId(viewId)) as View;
            if (view == null)
            {
                throw new Exception($"View {viewId} not found");
            }

            WorksetId wsId = new WorksetId(worksetId);
            WorksetVisibility visibility = view.GetWorksetVisibility(wsId);

            return new
            {
                viewId = viewId,
                viewName = view.Name,
                worksetId = worksetId,
                worksetName = doc.GetWorksetTable().GetWorkset(wsId).Name,
                visibility = visibility.ToString(),
                isVisible = visibility == WorksetVisibility.Visible
            };
        }

        #endregion
    }
}
