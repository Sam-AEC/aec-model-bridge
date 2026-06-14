using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using Autodesk.Navisworks.Api;
using Application = Autodesk.Navisworks.Api.Application;

namespace NavisworksBridge
{
    public static class BridgeCommands
    {
        [BridgeCommand("navis.get_document_info", IsMutating = false)]
        public static object GetDocumentInfo()
        {
            var doc = Application.ActiveDocument;
            return new
            {
                title = doc.Title ?? "",
                fileName = doc.FileName ?? "",
                isClear = doc.IsClear,
                modelsCount = doc.Models.Count
            };
        }

        [BridgeCommand("navis.get_model_tree", IsMutating = false)]
        public static object GetModelTree(JsonElement payload)
        {
            int maxDepth = payload.TryGetProperty("max_depth", out var md) ? md.GetInt32() : 2;
            var doc = Application.ActiveDocument;
            var rootItems = doc.Models.Select(m => m.RootItem);

            var tree = new List<object>();
            foreach (var root in rootItems)
            {
                tree.Add(SerializeModelItem(root, 0, maxDepth));
            }

            return new { models = tree };
        }

        private static object SerializeModelItem(ModelItem item, int currentDepth, int maxDepth)
        {
            var children = new List<object>();
            if (currentDepth < maxDepth)
            {
                foreach (var child in item.Children)
                {
                    children.Add(SerializeModelItem(child, currentDepth + 1, maxDepth));
                }
            }

            return new
            {
                displayName = item.DisplayName,
                className = item.ClassName,
                isLayer = item.IsLayer,
                isCollection = item.IsCollection,
                isInsert = item.IsInsert,
                isHidden = item.IsHidden,
                instanceGuid = item.InstanceGuid.ToString(),
                children = children
            };
        }

        [BridgeCommand("navis.get_selection", IsMutating = false)]
        public static object GetSelection()
        {
            var doc = Application.ActiveDocument;
            var selection = doc.CurrentSelection.SelectedItems;

            var items = new List<object>();
            foreach (var item in selection)
            {
                items.Add(new
                {
                    displayName = item.DisplayName,
                    className = item.ClassName,
                    instanceGuid = item.InstanceGuid.ToString()
                });
            }

            return new { count = items.Count, items = items };
        }

        [BridgeCommand("navis.append_file", IsMutating = true)]
        public static object AppendFile(JsonElement payload)
        {
            var doc = Application.ActiveDocument;
            var path = payload.GetProperty("path").GetString();
            
            if (string.IsNullOrEmpty(path) || !System.IO.File.Exists(path))
            {
                throw new ArgumentException("Valid path is required");
            }

            doc.AppendFile(path);
            
            return new
            {
                status = "success",
                appended_file = path,
                modelsCount = doc.Models.Count
            };
        }

        [BridgeCommand("navis.refresh", IsMutating = true)]
        public static object Refresh()
        {
            var doc = Application.ActiveDocument;
            doc.UpdateFiles();
            
            return new
            {
                status = "success",
                modelsCount = doc.Models.Count
            };
        }

        [BridgeCommand("navis.list_viewpoints", IsMutating = false)]
        public static object ListViewpoints()
        {
            var doc = Application.ActiveDocument;
            var viewpoints = doc.SavedViewpoints.RootItem.Children;

            var list = new List<object>();
            foreach (var vp in viewpoints)
            {
                list.Add(new
                {
                    displayName = vp.DisplayName,
                    isGroup = vp.IsGroup,
                    guid = vp.Guid.ToString()
                });
            }

            return new { count = list.Count, viewpoints = list };
        }

        [BridgeCommand("navis.create_viewpoint", IsMutating = true)]
        public static object CreateViewpoint(JsonElement payload)
        {
            var doc = Application.ActiveDocument;
            var name = payload.TryGetProperty("name", out var n) ? n.GetString() ?? "New Viewpoint" : "New Viewpoint";

            // CaptureRuntimeOverrides captures the current camera and state as a SavedViewpoint
            var captured = doc.SavedViewpoints.CaptureRuntimeOverrides();
            captured.DisplayName = name;
            doc.SavedViewpoints.AddCopy(captured);

            return new
            {
                status = "success",
                name = name
            };
        }

        [BridgeCommand("navis.activate_viewpoint", IsMutating = true)]
        public static object ActivateViewpoint(JsonElement payload)
        {
            var doc = Application.ActiveDocument;
            var guidStr = payload.GetProperty("guid").GetString();
            if (!Guid.TryParse(guidStr, out var guid))
            {
                throw new ArgumentException("Invalid GUID");
            }

            var vp = doc.SavedViewpoints.ResolveGuid(guid);
            if (vp == null)
            {
                throw new ArgumentException("Viewpoint not found");
            }

            if (!vp.IsGroup)
            {
                var savedVp = (SavedViewpoint)vp;
                doc.SavedViewpoints.CurrentSavedViewpoint = savedVp;
            }

            return new
            {
                status = "success",
                activated = vp.DisplayName
            };
        }
        [BridgeCommand("navis.invoke_method", IsMutating = true)]
        public static object InvokeMethod(JsonElement payload)
        {
            var doc = Application.ActiveDocument;
            var className = payload.GetProperty("class_name").GetString();
            var methodName = payload.GetProperty("method_name").GetString();
            var args = payload.GetProperty("arguments");
            var targetId = payload.TryGetProperty("target_id", out var tId) ? tId.GetString() : null;

            return ReflectionHelper.InvokeMethod(doc, className, methodName, args, targetId);
        }

        [BridgeCommand("navis.reflect_get", IsMutating = false)]
        public static object ReflectGet(JsonElement payload)
        {
            var doc = Application.ActiveDocument;
            var targetId = payload.GetProperty("target_id").GetString();
            var propertyName = payload.GetProperty("property_name").GetString();

            var target = ReflectionHelper.GetObject(targetId, doc);
            if (target == null) throw new Exception($"Target '{targetId}' not found");

            var prop = target.GetType().GetProperty(propertyName);
            if (prop == null) throw new Exception($"Property '{propertyName}' not found on type '{target.GetType().Name}'");

            var value = prop.GetValue(target);
            if (value == null) return null;
            if (value.GetType().IsPrimitive || value is string) return value;

            var refId = ReflectionHelper.RegisterObject(value);
            return new { type = "reference", id = refId, class_name = value.GetType().Name, str = value.ToString() };
        }

        [BridgeCommand("navis.reflect_set", IsMutating = true)]
        public static object ReflectSet(JsonElement payload)
        {
            var doc = Application.ActiveDocument;
            var targetId = payload.GetProperty("target_id").GetString();
            var propertyName = payload.GetProperty("property_name").GetString();
            var valueElement = payload.GetProperty("value");

            var target = ReflectionHelper.GetObject(targetId, doc);
            if (target == null) throw new Exception($"Target '{targetId}' not found");

            var prop = target.GetType().GetProperty(propertyName);
            if (prop == null) throw new Exception($"Property '{propertyName}' not found on type '{target.GetType().Name}'");

            var value = ReflectionHelper.ParseArgument(valueElement, doc);
            if (value != null && !prop.PropertyType.IsAssignableFrom(value.GetType()))
            {
                value = Convert.ChangeType(value, prop.PropertyType);
            }

            prop.SetValue(target, value);
            return new { status = "success", target_id = targetId, property = propertyName };
        }
    }
}
