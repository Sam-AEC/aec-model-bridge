using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevitBridge.Bridge;

public static class BridgeCommandFactory
{
    public static object Execute(UIApplication app, string tool, JsonElement payload)
    {
        return tool switch
        {
            // Existing 5 tools
            "revit.health" => ExecuteHealth(app),
            "revit.open_document" => ExecuteOpenDocument(app, payload),
            "revit.list_views" => ExecuteListViews(app),
            "revit.export_schedules" => ExecuteExportSchedules(app, payload),
            "revit.export_pdf_by_sheet_set" => ExecuteExportPdf(app, payload),

            // Document Management (5 new)
            "revit.save_document" => ExecuteSaveDocument(app, payload),
            "revit.close_document" => ExecuteCloseDocument(app, payload),
            "revit.create_new_document" => ExecuteCreateNewDocument(app, payload),
            "revit.get_document_info" => ExecuteGetDocumentInfo(app),
            "revit.list_levels" => ExecuteListLevels(app),

            // Geometry Creation (8 new)
            "revit.create_wall" => ExecuteCreateWall(app, payload),
            "revit.create_floor" => ExecuteCreateFloor(app, payload),
            "revit.create_roof" => ExecuteCreateRoof(app, payload),
            "revit.create_level" => ExecuteCreateLevel(app, payload),
            "revit.create_grid" => ExecuteCreateGrid(app, payload),
            "revit.create_room" => ExecuteCreateRoom(app, payload),
            "revit.list_elements_by_category" => ExecuteListElementsByCategory(app, payload),
            "revit.delete_element" => ExecuteDeleteElement(app, payload),

            // Component Placement (4 new)
            "revit.place_family_instance" => ExecutePlaceFamilyInstance(app, payload),
            "revit.place_door" => ExecutePlaceDoor(app, payload),
            "revit.place_window" => ExecutePlaceWindow(app, payload),
            "revit.list_families" => ExecuteListFamilies(app, payload),

            // View Creation (3 new)
            "revit.create_floor_plan_view" => ExecuteCreateFloorPlanView(app, payload),
            "revit.create_3d_view" => ExecuteCreate3DView(app, payload),
            "revit.create_section_view" => ExecuteCreateSectionView(app, payload),

            _ => new { status = "error", message = $"Unknown tool: {tool}" }
        };
    }

    public static List<string> GetToolCatalog()
    {
        return new List<string>
        {
            // Original 5
            "revit.health",
            "revit.open_document",
            "revit.list_views",
            "revit.export_schedules",
            "revit.export_pdf_by_sheet_set",

            // Document Management
            "revit.save_document",
            "revit.close_document",
            "revit.create_new_document",
            "revit.get_document_info",
            "revit.list_levels",

            // Geometry Creation
            "revit.create_wall",
            "revit.create_floor",
            "revit.create_roof",
            "revit.create_level",
            "revit.create_grid",
            "revit.create_room",
            "revit.list_elements_by_category",
            "revit.delete_element",

            // Component Placement
            "revit.place_family_instance",
            "revit.place_door",
            "revit.place_window",
            "revit.list_families",

            // View Creation
            "revit.create_floor_plan_view",
            "revit.create_3d_view",
            "revit.create_section_view"
        };
    }

    // ==================== EXISTING TOOLS ====================

    private static object ExecuteHealth(UIApplication app)
    {
        var doc = app.ActiveUIDocument?.Document;
        return new
        {
            status = "healthy",
            revit_version = app.Application.VersionNumber,
            revit_build = app.Application.VersionBuild,
            active_document = doc?.Title ?? "none",
            document_is_modified = doc?.IsModified ?? false,
            username = app.Application.Username
        };
    }

    private static object ExecuteOpenDocument(UIApplication app, JsonElement payload)
    {
        var path = payload.GetProperty("path").GetString();
        if (string.IsNullOrEmpty(path))
            throw new ArgumentException("Missing 'path' parameter");

        var docPath = new FilePath(path);
        var openOptions = new OpenOptions();
        var doc = app.Application.OpenDocumentFile(docPath, openOptions);

        return new
        {
            path = doc.PathName,
            title = doc.Title,
            is_family = doc.IsFamilyDocument,
            is_modified = doc.IsModified
        };
    }

    private static object ExecuteListViews(UIApplication app)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var views = new FilteredElementCollector(doc)
            .OfClass(typeof(View))
            .Cast<View>()
            .Where(v => !v.IsTemplate)
            .Select(v => new
            {
                id = v.Id.IntegerValue,
                name = v.Name,
                type = v.ViewType.ToString(),
                scale = v.Scale,
                detail_level = v.DetailLevel.ToString()
            })
            .ToList();

        return new { views, count = views.Count };
    }

    private static object ExecuteExportSchedules(UIApplication app, JsonElement payload)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var outputPath = payload.GetProperty("output_path").GetString();
        if (string.IsNullOrEmpty(outputPath))
            throw new ArgumentException("Missing 'output_path' parameter");

        var schedules = new FilteredElementCollector(doc)
            .OfClass(typeof(ViewSchedule))
            .Cast<ViewSchedule>()
            .ToList();

        var exported = new List<string>();

        using (var trans = new Transaction(doc, "Export Schedules"))
        {
            trans.Start();

            foreach (var schedule in schedules)
            {
                try
                {
                    var options = new ViewScheduleExportOptions
                    {
                        Title = false,
                        FieldDelimiter = ",",
                        TextQualifier = ExportTextQualifier.DoubleQuote
                    };

                    var filename = $"{SanitizeFileName(schedule.Name)}.csv";
                    var fullPath = System.IO.Path.Combine(outputPath, filename);
                    schedule.Export(outputPath, filename, options);
                    exported.Add(fullPath);
                }
                catch (Exception ex)
                {
                    Serilog.Log.Warning(ex, "Failed to export schedule {ScheduleName}", schedule.Name);
                }
            }

            trans.Commit();
        }

        return new { schedules = exported, count = exported.Count };
    }

    private static object ExecuteExportPdf(UIApplication app, JsonElement payload)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var outputPath = payload.GetProperty("output_path").GetString();
        if (string.IsNullOrEmpty(outputPath))
            throw new ArgumentException("Missing 'output_path' parameter");

        var sheets = new FilteredElementCollector(doc)
            .OfClass(typeof(ViewSheet))
            .Cast<ViewSheet>()
            .Where(s => !s.IsPlaceholder)
            .Select(s => s.Id)
            .ToList();

        if (sheets.Count == 0)
        {
            return new
            {
                output_path = outputPath,
                sheets_exported = 0,
                status = "no_sheets",
                message = "No sheets found in document"
            };
        }

        var options = new PDFExportOptions
        {
            FileName = System.IO.Path.GetFileNameWithoutExtension(outputPath),
            Combine = true
        };

        var exportDir = System.IO.Path.GetDirectoryName(outputPath);
        doc.Export(exportDir, sheets, options);

        return new
        {
            output_path = outputPath,
            sheets_exported = sheets.Count,
            status = "exported"
        };
    }

    // ==================== DOCUMENT MANAGEMENT (5 NEW) ====================

    private static object ExecuteSaveDocument(UIApplication app, JsonElement payload)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var savePath = payload.TryGetProperty("path", out var pathProp) ? pathProp.GetString() : null;

        if (!string.IsNullOrEmpty(savePath))
        {
            // Save As
            var saveAsOptions = new SaveAsOptions { OverwriteExistingFile = true };
            doc.SaveAs(savePath, saveAsOptions);
            return new { path = savePath, saved_as = true };
        }
        else
        {
            // Save
            doc.Save();
            return new { path = doc.PathName, saved_as = false };
        }
    }

    private static object ExecuteCloseDocument(UIApplication app, JsonElement payload)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var saveChanges = payload.TryGetProperty("save_changes", out var saveProp) && saveProp.GetBoolean();
        var title = doc.Title;

        if (saveChanges && doc.IsModified)
        {
            doc.Save();
        }

        doc.Close(saveChanges);
        return new { closed = title, saved = saveChanges };
    }

    private static object ExecuteCreateNewDocument(UIApplication app, JsonElement payload)
    {
        var templatePath = payload.TryGetProperty("template_path", out var tpl) ? tpl.GetString() : null;

        Document doc;
        if (!string.IsNullOrEmpty(templatePath))
        {
            doc = app.Application.NewProjectDocument(templatePath);
        }
        else
        {
            doc = app.Application.NewProjectDocument(UnitSystem.Metric);
        }

        return new
        {
            title = doc.Title,
            path = doc.PathName ?? "unsaved",
            is_modified = doc.IsModified
        };
    }

    private static object ExecuteGetDocumentInfo(UIApplication app)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var projectInfo = doc.ProjectInformation;

        return new
        {
            title = doc.Title,
            path = doc.PathName ?? "unsaved",
            is_modified = doc.IsModified,
            is_family = doc.IsFamilyDocument,
            is_workshared = doc.IsWorkshared,
            project_name = projectInfo?.get_Parameter(BuiltInParameter.PROJECT_NAME)?.AsString(),
            project_number = projectInfo?.get_Parameter(BuiltInParameter.PROJECT_NUMBER)?.AsString(),
            project_address = projectInfo?.get_Parameter(BuiltInParameter.PROJECT_ADDRESS)?.AsString(),
            project_status = projectInfo?.get_Parameter(BuiltInParameter.PROJECT_STATUS)?.AsString()
        };
    }

    private static object ExecuteListLevels(UIApplication app)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var levels = new FilteredElementCollector(doc)
            .OfClass(typeof(Level))
            .Cast<Level>()
            .OrderBy(l => l.Elevation)
            .Select(l => new
            {
                id = l.Id.IntegerValue,
                name = l.Name,
                elevation = l.Elevation,
                elevation_ft = l.Elevation,
                elevation_m = UnitUtils.ConvertFromInternalUnits(l.Elevation, UnitTypeId.Meters)
            })
            .ToList();

        return new { levels, count = levels.Count };
    }

    // ==================== GEOMETRY CREATION (8 NEW) ====================

    private static object ExecuteCreateWall(UIApplication app, JsonElement payload)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var startPoint = ParseXYZ(payload.GetProperty("start_point"));
        var endPoint = ParseXYZ(payload.GetProperty("end_point"));
        var height = payload.GetProperty("height").GetDouble();
        var levelName = payload.GetProperty("level").GetString();
        var wallTypeName = payload.TryGetProperty("wall_type", out var wt) ? wt.GetString() : null;

        using (var trans = new Transaction(doc, "Create Wall"))
        {
            trans.Start();

            var level = GetLevelByName(doc, levelName);
            var line = Line.CreateBound(startPoint, endPoint);

            Wall wall;
            if (!string.IsNullOrEmpty(wallTypeName))
            {
                var wallType = GetWallTypeByName(doc, wallTypeName);
                wall = Wall.Create(doc, line, wallType.Id, level.Id, height, 0, false, false);
            }
            else
            {
                wall = Wall.Create(doc, line, level.Id, false);
                var param = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);
                if (param != null && !param.IsReadOnly)
                {
                    param.Set(height);
                }
            }

            trans.Commit();

            return new
            {
                wall_id = wall.Id.IntegerValue,
                length = line.Length,
                length_ft = line.Length,
                length_m = UnitUtils.ConvertFromInternalUnits(line.Length, UnitTypeId.Meters),
                height = height
            };
        }
    }

    private static object ExecuteCreateFloor(UIApplication app, JsonElement payload)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var boundaryPoints = ParsePointArray(payload.GetProperty("boundary_points"));
        var levelName = payload.GetProperty("level").GetString();
        var floorTypeName = payload.TryGetProperty("floor_type", out var ft) ? ft.GetString() : null;

        using (var trans = new Transaction(doc, "Create Floor"))
        {
            trans.Start();

            var level = GetLevelByName(doc, levelName);
            var curveArray = new CurveArray();

            for (int i = 0; i < boundaryPoints.Count; i++)
            {
                var start = boundaryPoints[i];
                var end = boundaryPoints[(i + 1) % boundaryPoints.Count];
                curveArray.Append(Line.CreateBound(start, end));
            }

            Floor floor;
            if (!string.IsNullOrEmpty(floorTypeName))
            {
                var floorType = GetFloorTypeByName(doc, floorTypeName);
                floor = doc.Create.NewFloor(curveArray, floorType, level, false);
            }
            else
            {
                floor = doc.Create.NewFloor(curveArray, false);
            }

            trans.Commit();

            var area = floor.get_Parameter(BuiltInParameter.HOST_AREA_COMPUTED)?.AsDouble() ?? 0;

            return new
            {
                floor_id = floor.Id.IntegerValue,
                area_sf = area,
                area_sm = UnitUtils.ConvertFromInternalUnits(area, UnitTypeId.SquareMeters),
                level = levelName
            };
        }
    }

    private static object ExecuteCreateRoof(UIApplication app, JsonElement payload)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var boundaryPoints = ParsePointArray(payload.GetProperty("boundary_points"));
        var levelName = payload.GetProperty("level").GetString();
        var roofTypeName = payload.TryGetProperty("roof_type", out var rt) ? rt.GetString() : null;

        using (var trans = new Transaction(doc, "Create Roof"))
        {
            trans.Start();

            var level = GetLevelByName(doc, levelName);
            var curveArray = new CurveArray();

            for (int i = 0; i < boundaryPoints.Count; i++)
            {
                var start = boundaryPoints[i];
                var end = boundaryPoints[(i + 1) % boundaryPoints.Count];
                curveArray.Append(Line.CreateBound(start, end));
            }

            RoofType roofType = null;
            if (!string.IsNullOrEmpty(roofTypeName))
            {
                roofType = GetRoofTypeByName(doc, roofTypeName);
            }

            var modelCurveArray = new ModelCurveArray();
            var footprint = doc.Create.NewFootPrintRoof(curveArray, level, roofType, out modelCurveArray);

            trans.Commit();

            return new
            {
                roof_id = footprint.Id.IntegerValue,
                level = levelName,
                curve_count = curveArray.Size
            };
        }
    }

    private static object ExecuteCreateLevel(UIApplication app, JsonElement payload)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var name = payload.GetProperty("name").GetString();
        var elevation = payload.GetProperty("elevation").GetDouble();

        using (var trans = new Transaction(doc, "Create Level"))
        {
            trans.Start();

            var level = Level.Create(doc, elevation);
            level.Name = name;

            trans.Commit();

            return new
            {
                level_id = level.Id.IntegerValue,
                name = level.Name,
                elevation = level.Elevation,
                elevation_ft = level.Elevation,
                elevation_m = UnitUtils.ConvertFromInternalUnits(level.Elevation, UnitTypeId.Meters)
            };
        }
    }

    private static object ExecuteCreateGrid(UIApplication app, JsonElement payload)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var startPoint = ParseXYZ(payload.GetProperty("start_point"));
        var endPoint = ParseXYZ(payload.GetProperty("end_point"));
        var name = payload.TryGetProperty("name", out var n) ? n.GetString() : null;

        using (var trans = new Transaction(doc, "Create Grid"))
        {
            trans.Start();

            var line = Line.CreateBound(startPoint, endPoint);
            var grid = Grid.Create(doc, line);

            if (!string.IsNullOrEmpty(name))
            {
                grid.Name = name;
            }

            trans.Commit();

            return new
            {
                grid_id = grid.Id.IntegerValue,
                name = grid.Name,
                curve_type = grid.Curve.GetType().Name
            };
        }
    }

    private static object ExecuteCreateRoom(UIApplication app, JsonElement payload)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var locationPoint = ParseXYZ(payload.GetProperty("location_point"));
        var levelName = payload.GetProperty("level").GetString();
        var roomName = payload.TryGetProperty("name", out var n) ? n.GetString() : "Room";
        var roomNumber = payload.TryGetProperty("number", out var num) ? num.GetString() : null;

        using (var trans = new Transaction(doc, "Create Room"))
        {
            trans.Start();

            var level = GetLevelByName(doc, levelName);
            var uvPoint = new UV(locationPoint.X, locationPoint.Y);
            var room = doc.Create.NewRoom(level, uvPoint);

            if (!string.IsNullOrEmpty(roomName))
            {
                room.Name = roomName;
            }

            if (!string.IsNullOrEmpty(roomNumber))
            {
                room.Number = roomNumber;
            }

            trans.Commit();

            var area = room.Area;
            var volume = room.Volume;

            return new
            {
                room_id = room.Id.IntegerValue,
                name = room.Name,
                number = room.Number,
                area_sf = area,
                area_sm = UnitUtils.ConvertFromInternalUnits(area, UnitTypeId.SquareMeters),
                volume_cf = volume,
                volume_cm = UnitUtils.ConvertFromInternalUnits(volume, UnitTypeId.CubicMeters)
            };
        }
    }

    private static object ExecuteListElementsByCategory(UIApplication app, JsonElement payload)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var categoryName = payload.GetProperty("category").GetString();
        var category = GetCategoryByName(doc, categoryName);

        var elements = new FilteredElementCollector(doc)
            .OfCategoryId(category.Id)
            .WhereElementIsNotElementType()
            .Select(e => new
            {
                id = e.Id.IntegerValue,
                name = e.Name,
                category = e.Category?.Name,
                type = doc.GetElement(e.GetTypeId())?.Name
            })
            .ToList();

        return new { elements, count = elements.Count, category = categoryName };
    }

    private static object ExecuteDeleteElement(UIApplication app, JsonElement payload)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var elementId = payload.GetProperty("element_id").GetInt32();

        using (var trans = new Transaction(doc, "Delete Element"))
        {
            trans.Start();

            var id = new ElementId(elementId);
            var deletedIds = doc.Delete(id);

            trans.Commit();

            return new
            {
                deleted_count = deletedIds.Count,
                deleted_ids = deletedIds.Select(i => i.IntegerValue).ToList()
            };
        }
    }

    // ==================== COMPONENT PLACEMENT (4 NEW) ====================

    private static object ExecutePlaceFamilyInstance(UIApplication app, JsonElement payload)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var location = ParseXYZ(payload.GetProperty("location"));
        var familyName = payload.GetProperty("family_name").GetString();
        var typeName = payload.GetProperty("type_name").GetString();
        var levelName = payload.GetProperty("level").GetString();

        using (var trans = new Transaction(doc, "Place Family Instance"))
        {
            trans.Start();

            var level = GetLevelByName(doc, levelName);
            var familySymbol = GetFamilySymbolByName(doc, familyName, typeName);

            if (!familySymbol.IsActive)
            {
                familySymbol.Activate();
                doc.Regenerate();
            }

            var instance = doc.Create.NewFamilyInstance(location, familySymbol, level, Autodesk.Revit.DB.Structure.StructuralType.NonStructural);

            trans.Commit();

            return new
            {
                instance_id = instance.Id.IntegerValue,
                family = familyName,
                type = typeName,
                level = levelName
            };
        }
    }

    private static object ExecutePlaceDoor(UIApplication app, JsonElement payload)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var wallId = payload.GetProperty("wall_id").GetInt32();
        var location = ParseXYZ(payload.GetProperty("location"));
        var familyName = payload.TryGetProperty("family_name", out var fn) ? fn.GetString() : "Single-Flush";
        var typeName = payload.TryGetProperty("type_name", out var tn) ? tn.GetString() : "0915 x 2134mm";

        using (var trans = new Transaction(doc, "Place Door"))
        {
            trans.Start();

            var wall = doc.GetElement(new ElementId(wallId)) as Wall;
            if (wall == null)
                throw new ArgumentException($"Wall with ID {wallId} not found");

            var familySymbol = GetFamilySymbolByName(doc, familyName, typeName);

            if (!familySymbol.IsActive)
            {
                familySymbol.Activate();
                doc.Regenerate();
            }

            var door = doc.Create.NewFamilyInstance(location, familySymbol, wall, Autodesk.Revit.DB.Structure.StructuralType.NonStructural);

            trans.Commit();

            return new
            {
                door_id = door.Id.IntegerValue,
                family = familyName,
                type = typeName,
                wall_id = wallId
            };
        }
    }

    private static object ExecutePlaceWindow(UIApplication app, JsonElement payload)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var wallId = payload.GetProperty("wall_id").GetInt32();
        var location = ParseXYZ(payload.GetProperty("location"));
        var familyName = payload.TryGetProperty("family_name", out var fn) ? fn.GetString() : "Fixed";
        var typeName = payload.TryGetProperty("type_name", out var tn) ? tn.GetString() : "1200 x 1500mm";

        using (var trans = new Transaction(doc, "Place Window"))
        {
            trans.Start();

            var wall = doc.GetElement(new ElementId(wallId)) as Wall;
            if (wall == null)
                throw new ArgumentException($"Wall with ID {wallId} not found");

            var familySymbol = GetFamilySymbolByName(doc, familyName, typeName);

            if (!familySymbol.IsActive)
            {
                familySymbol.Activate();
                doc.Regenerate();
            }

            var window = doc.Create.NewFamilyInstance(location, familySymbol, wall, Autodesk.Revit.DB.Structure.StructuralType.NonStructural);

            trans.Commit();

            return new
            {
                window_id = window.Id.IntegerValue,
                family = familyName,
                type = typeName,
                wall_id = wallId
            };
        }
    }

    private static object ExecuteListFamilies(UIApplication app, JsonElement payload)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var categoryFilter = payload.TryGetProperty("category", out var cat) ? cat.GetString() : null;

        var families = new FilteredElementCollector(doc)
            .OfClass(typeof(Family))
            .Cast<Family>()
            .Where(f => string.IsNullOrEmpty(categoryFilter) ||
                       f.FamilyCategory?.Name.Equals(categoryFilter, StringComparison.OrdinalIgnoreCase) == true)
            .Select(f => new
            {
                family_id = f.Id.IntegerValue,
                name = f.Name,
                category = f.FamilyCategory?.Name,
                types = GetFamilySymbols(doc, f).Select(fs => new
                {
                    type_id = fs.Id.IntegerValue,
                    name = fs.Name
                }).ToList()
            })
            .ToList();

        return new { families, count = families.Count };
    }

    // ==================== VIEW CREATION (3 NEW) ====================

    private static object ExecuteCreateFloorPlanView(UIApplication app, JsonElement payload)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var levelName = payload.GetProperty("level").GetString();
        var viewName = payload.TryGetProperty("name", out var n) ? n.GetString() : null;

        using (var trans = new Transaction(doc, "Create Floor Plan View"))
        {
            trans.Start();

            var level = GetLevelByName(doc, levelName);
            var viewFamilyType = GetViewFamilyType(doc, ViewFamily.FloorPlan);

            var view = ViewPlan.Create(doc, viewFamilyType.Id, level.Id);

            if (!string.IsNullOrEmpty(viewName))
            {
                view.Name = viewName;
            }

            trans.Commit();

            return new
            {
                view_id = view.Id.IntegerValue,
                name = view.Name,
                level = levelName,
                view_type = view.ViewType.ToString()
            };
        }
    }

    private static object ExecuteCreate3DView(UIApplication app, JsonElement payload)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var viewName = payload.TryGetProperty("name", out var n) ? n.GetString() : "3D View";

        using (var trans = new Transaction(doc, "Create 3D View"))
        {
            trans.Start();

            var viewFamilyType = GetViewFamilyType(doc, ViewFamily.ThreeDimensional);
            var view3d = View3D.CreateIsometric(doc, viewFamilyType.Id);
            view3d.Name = viewName;

            trans.Commit();

            return new
            {
                view_id = view3d.Id.IntegerValue,
                name = view3d.Name,
                view_type = view3d.ViewType.ToString()
            };
        }
    }

    private static object ExecuteCreateSectionView(UIApplication app, JsonElement payload)
    {
        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");

        var startPoint = ParseXYZ(payload.GetProperty("start_point"));
        var endPoint = ParseXYZ(payload.GetProperty("end_point"));
        var viewName = payload.TryGetProperty("name", out var n) ? n.GetString() : "Section";

        using (var trans = new Transaction(doc, "Create Section View"))
        {
            trans.Start();

            var viewFamilyType = GetViewFamilyType(doc, ViewFamily.Section);

            // Create bounding box for section
            var direction = (endPoint - startPoint).Normalize();
            var up = XYZ.BasisZ;
            var viewDirection = new XYZ(-direction.Y, direction.X, 0);

            var transform = Transform.Identity;
            transform.Origin = (startPoint + endPoint) / 2;
            transform.BasisX = direction;
            transform.BasisY = up;
            transform.BasisZ = viewDirection;

            var min = new XYZ(-10, -10, -10);
            var max = new XYZ(10, 10, 10);
            var bbox = new BoundingBoxXYZ { Transform = transform, Min = min, Max = max };

            var section = ViewSection.CreateSection(doc, viewFamilyType.Id, bbox);
            section.Name = viewName;

            trans.Commit();

            return new
            {
                view_id = section.Id.IntegerValue,
                name = section.Name,
                view_type = section.ViewType.ToString()
            };
        }
    }

    // ==================== HELPER METHODS ====================

    private static XYZ ParseXYZ(JsonElement element)
    {
        if (element.ValueKind == JsonValueKind.Array)
        {
            var array = element.EnumerateArray().Select(e => e.GetDouble()).ToArray();
            return new XYZ(array[0], array[1], array.Length > 2 ? array[2] : 0);
        }

        var x = element.GetProperty("x").GetDouble();
        var y = element.GetProperty("y").GetDouble();
        var z = element.TryGetProperty("z", out var zProp) ? zProp.GetDouble() : 0;
        return new XYZ(x, y, z);
    }

    private static List<XYZ> ParsePointArray(JsonElement element)
    {
        return element.EnumerateArray()
            .Select(ParseXYZ)
            .ToList();
    }

    private static Level GetLevelByName(Document doc, string name)
    {
        var level = new FilteredElementCollector(doc)
            .OfClass(typeof(Level))
            .Cast<Level>()
            .FirstOrDefault(l => l.Name.Equals(name, StringComparison.OrdinalIgnoreCase));

        if (level == null)
            throw new ArgumentException($"Level '{name}' not found");

        return level;
    }

    private static WallType GetWallTypeByName(Document doc, string name)
    {
        var wallType = new FilteredElementCollector(doc)
            .OfClass(typeof(WallType))
            .Cast<WallType>()
            .FirstOrDefault(wt => wt.Name.Equals(name, StringComparison.OrdinalIgnoreCase));

        if (wallType == null)
            throw new ArgumentException($"Wall type '{name}' not found");

        return wallType;
    }

    private static FloorType GetFloorTypeByName(Document doc, string name)
    {
        var floorType = new FilteredElementCollector(doc)
            .OfClass(typeof(FloorType))
            .Cast<FloorType>()
            .FirstOrDefault(ft => ft.Name.Equals(name, StringComparison.OrdinalIgnoreCase));

        if (floorType == null)
            throw new ArgumentException($"Floor type '{name}' not found");

        return floorType;
    }

    private static RoofType GetRoofTypeByName(Document doc, string name)
    {
        var roofType = new FilteredElementCollector(doc)
            .OfClass(typeof(RoofType))
            .Cast<RoofType>()
            .FirstOrDefault(rt => rt.Name.Equals(name, StringComparison.OrdinalIgnoreCase));

        if (roofType == null)
            throw new ArgumentException($"Roof type '{name}' not found");

        return roofType;
    }

    private static Category GetCategoryByName(Document doc, string name)
    {
        var category = doc.Settings.Categories.Cast<Category>()
            .FirstOrDefault(c => c.Name.Equals(name, StringComparison.OrdinalIgnoreCase));

        if (category == null)
            throw new ArgumentException($"Category '{name}' not found");

        return category;
    }

    private static FamilySymbol GetFamilySymbolByName(Document doc, string familyName, string typeName)
    {
        var familySymbol = new FilteredElementCollector(doc)
            .OfClass(typeof(FamilySymbol))
            .Cast<FamilySymbol>()
            .FirstOrDefault(fs =>
                fs.Family.Name.Equals(familyName, StringComparison.OrdinalIgnoreCase) &&
                fs.Name.Equals(typeName, StringComparison.OrdinalIgnoreCase));

        if (familySymbol == null)
            throw new ArgumentException($"Family symbol '{familyName}: {typeName}' not found");

        return familySymbol;
    }

    private static IEnumerable<FamilySymbol> GetFamilySymbols(Document doc, Family family)
    {
        return family.GetFamilySymbolIds()
            .Select(id => doc.GetElement(id) as FamilySymbol)
            .Where(fs => fs != null);
    }

    private static ViewFamilyType GetViewFamilyType(Document doc, ViewFamily viewFamily)
    {
        var vft = new FilteredElementCollector(doc)
            .OfClass(typeof(ViewFamilyType))
            .Cast<ViewFamilyType>()
            .FirstOrDefault(x => x.ViewFamily == viewFamily);

        if (vft == null)
            throw new ArgumentException($"View family type for '{viewFamily}' not found");

        return vft;
    }

    private static string SanitizeFileName(string fileName)
    {
        var invalidChars = System.IO.Path.GetInvalidFileNameChars();
        return new string(fileName.Select(c => invalidChars.Contains(c) ? '_' : c).ToArray());
    }
}
