using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Structure;
using Autodesk.Revit.UI;

namespace RevitBridge.Commands.Specialized.Structural
{
    /// <summary>
    /// Structural engineering commands for framing, loads, and analysis
    /// StructuralType (#344, Score: 159), AnalyticalModel (#372, Score: 155)
    /// </summary>
    public static class StructuralCommands
    {
        #region 1. Create Structural Framing

        public static object CreateStructuralFraming(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int familySymbolId = payload.GetProperty("family_symbol_id").GetInt32();
            var startPoint = payload.GetProperty("start_point");
            var endPoint = payload.GetProperty("end_point");
            int levelId = payload.GetProperty("level_id").GetInt32();

            XYZ start = new XYZ(
                startPoint.GetProperty("x").GetDouble(),
                startPoint.GetProperty("y").GetDouble(),
                startPoint.GetProperty("z").GetDouble()
            );

            XYZ end = new XYZ(
                endPoint.GetProperty("x").GetDouble(),
                endPoint.GetProperty("y").GetDouble(),
                endPoint.GetProperty("z").GetDouble()
            );

            using (var trans = new Transaction(doc, "Create Structural Framing"))
            {
                trans.Start();

                FamilySymbol symbol = doc.GetElement(new ElementId(familySymbolId)) as FamilySymbol;
                if (symbol == null)
                {
                    throw new Exception($"Family symbol {familySymbolId} not found");
                }

                if (!symbol.IsActive)
                {
                    symbol.Activate();
                }

                Level level = doc.GetElement(new ElementId(levelId)) as Level;
                if (level == null)
                {
                    throw new Exception($"Level {levelId} not found");
                }

                // Create line
                Line line = Line.CreateBound(start, end);

                // Create structural framing instance
                FamilyInstance framing = doc.Create.NewFamilyInstance(
                    line,
                    symbol,
                    level,
                    StructuralType.Beam
                );

                trans.Commit();

                return new
                {
                    success = true,
                    framingId = framing.Id.IntegerValue,
                    familyName = symbol.FamilyName,
                    typeName = symbol.Name,
                    length = line.Length,
                    structuralType = "Beam"
                };
            }
        }

        #endregion

        #region 2. Create Structural Column

        public static object CreateStructuralColumn(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int familySymbolId = payload.GetProperty("family_symbol_id").GetInt32();
            var locationPoint = payload.GetProperty("location");
            int baseLevelId = payload.GetProperty("base_level_id").GetInt32();
            int topLevelId = payload.GetProperty("top_level_id").GetInt32();

            XYZ location = new XYZ(
                locationPoint.GetProperty("x").GetDouble(),
                locationPoint.GetProperty("y").GetDouble(),
                locationPoint.GetProperty("z").GetDouble()
            );

            using (var trans = new Transaction(doc, "Create Structural Column"))
            {
                trans.Start();

                FamilySymbol symbol = doc.GetElement(new ElementId(familySymbolId)) as FamilySymbol;
                if (symbol == null)
                {
                    throw new Exception($"Family symbol {familySymbolId} not found");
                }

                if (!symbol.IsActive)
                {
                    symbol.Activate();
                }

                Level baseLevel = doc.GetElement(new ElementId(baseLevelId)) as Level;
                Level topLevel = doc.GetElement(new ElementId(topLevelId)) as Level;

                if (baseLevel == null || topLevel == null)
                {
                    throw new Exception("Base or top level not found");
                }

                // Create structural column
                FamilyInstance column = doc.Create.NewFamilyInstance(
                    location,
                    symbol,
                    baseLevel,
                    StructuralType.Column
                );

                // Set top level
                Parameter topLevelParam = column.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_PARAM);
                if (topLevelParam != null)
                {
                    topLevelParam.Set(topLevel.Id);
                }

                trans.Commit();

                double height = topLevel.Elevation - baseLevel.Elevation;

                return new
                {
                    success = true,
                    columnId = column.Id.IntegerValue,
                    familyName = symbol.FamilyName,
                    typeName = symbol.Name,
                    baseLevelId = baseLevelId,
                    topLevelId = topLevelId,
                    height = height,
                    structuralType = "Column"
                };
            }
        }

        #endregion

        #region 3. Create Truss

        public static object CreateTruss(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int familySymbolId = payload.GetProperty("family_symbol_id").GetInt32();
            var startPoint = payload.GetProperty("start_point");
            var endPoint = payload.GetProperty("end_point");
            int levelId = payload.GetProperty("level_id").GetInt32();

            XYZ start = new XYZ(
                startPoint.GetProperty("x").GetDouble(),
                startPoint.GetProperty("y").GetDouble(),
                startPoint.GetProperty("z").GetDouble()
            );

            XYZ end = new XYZ(
                endPoint.GetProperty("x").GetDouble(),
                endPoint.GetProperty("y").GetDouble(),
                endPoint.GetProperty("z").GetDouble()
            );

            using (var trans = new Transaction(doc, "Create Truss"))
            {
                trans.Start();

                FamilySymbol symbol = doc.GetElement(new ElementId(familySymbolId)) as FamilySymbol;
                if (symbol == null)
                {
                    throw new Exception($"Family symbol {familySymbolId} not found");
                }

                if (!symbol.IsActive)
                {
                    symbol.Activate();
                }

                Level level = doc.GetElement(new ElementId(levelId)) as Level;
                if (level == null)
                {
                    throw new Exception($"Level {levelId} not found");
                }

                // Create line for truss
                Line line = Line.CreateBound(start, end);

                // Create truss instance
                FamilyInstance truss = doc.Create.NewFamilyInstance(
                    line,
                    symbol,
                    level,
                    StructuralType.Beam
                );

                trans.Commit();

                return new
                {
                    success = true,
                    trussId = truss.Id.IntegerValue,
                    familyName = symbol.FamilyName,
                    typeName = symbol.Name,
                    length = line.Length,
                    structuralType = "Truss"
                };
            }
        }

        #endregion

        #region 4. Place Rebar

        public static object PlaceRebar(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int hostElementId = payload.GetProperty("host_element_id").GetInt32();
            int rebarBarTypeId = payload.GetProperty("rebar_bar_type_id").GetInt32();
            int rebarShapeId = payload.GetProperty("rebar_shape_id").GetInt32();

            using (var trans = new Transaction(doc, "Place Rebar"))
            {
                trans.Start();

                try
                {
                    Element hostElement = doc.GetElement(new ElementId(hostElementId));
                    RebarBarType barType = doc.GetElement(new ElementId(rebarBarTypeId)) as RebarBarType;
                    RebarShape shape = doc.GetElement(new ElementId(rebarShapeId)) as RebarShape;

                    if (hostElement == null || barType == null || shape == null)
                    {
                        throw new Exception("Host element, bar type, or shape not found");
                    }

                    // Get host face
                    var faces = GetFaces(hostElement);
                    if (faces == null || faces.Count == 0)
                    {
                        throw new Exception("Could not get faces from host element");
                    }

                    Face hostFace = faces[0];

                    // Create rebar
                    XYZ origin = new XYZ(0, 0, 0);
                    XYZ xVec = new XYZ(1, 0, 0);
                    XYZ yVec = new XYZ(0, 1, 0);

                    Rebar rebar = Rebar.CreateFromRebarShape(
                        doc,
                        shape,
                        barType,
                        hostElement,
                        origin,
                        xVec,
                        yVec
                    );

                    trans.Commit();

                    return new
                    {
                        success = true,
                        rebarId = rebar.Id.IntegerValue,
                        hostElementId = hostElementId,
                        barTypeName = barType.Name,
                        shapeName = shape.Name
                    };
                }
                catch (Exception ex)
                {
                    return new { success = false, error = ex.Message };
                }
            }
        }

        #endregion

        #region 5. Create Load Case

        public static object CreateLoadCase(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            string caseName = payload.GetProperty("case_name").GetString();
            int natureId = payload.GetProperty("nature_id").GetInt32(); // LoadNature enum value

            using (var trans = new Transaction(doc, "Create Load Case"))
            {
                trans.Start();

                try
                {
                    LoadNature nature = (LoadNature)natureId;
                    LoadCase loadCase = LoadCase.Create(doc, caseName, nature, 0);

                    trans.Commit();

                    return new
                    {
                        success = true,
                        loadCaseId = loadCase.Id.IntegerValue,
                        caseName = loadCase.Name,
                        nature = nature.ToString()
                    };
                }
                catch (Exception ex)
                {
                    return new { success = false, error = ex.Message };
                }
            }
        }

        #endregion

        #region 6. Apply Point Load

        public static object ApplyPointLoad(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int hostElementId = payload.GetProperty("host_element_id").GetInt32();
            var forceVector = payload.GetProperty("force_vector");
            var loadPoint = payload.GetProperty("load_point");

            XYZ force = new XYZ(
                forceVector.GetProperty("x").GetDouble(),
                forceVector.GetProperty("y").GetDouble(),
                forceVector.GetProperty("z").GetDouble()
            );

            XYZ point = new XYZ(
                loadPoint.GetProperty("x").GetDouble(),
                loadPoint.GetProperty("y").GetDouble(),
                loadPoint.GetProperty("z").GetDouble()
            );

            using (var trans = new Transaction(doc, "Apply Point Load"))
            {
                trans.Start();

                try
                {
                    Element hostElement = doc.GetElement(new ElementId(hostElementId));
                    if (hostElement == null)
                    {
                        throw new Exception($"Host element {hostElementId} not found");
                    }

                    // Create point load
                    PointLoad pointLoad = PointLoad.Create(doc, new ElementId(hostElementId), force, point);

                    trans.Commit();

                    return new
                    {
                        success = true,
                        loadId = pointLoad.Id.IntegerValue,
                        hostElementId = hostElementId,
                        force = new { x = force.X, y = force.Y, z = force.Z },
                        location = new { x = point.X, y = point.Y, z = point.Z }
                    };
                }
                catch (Exception ex)
                {
                    return new { success = false, error = ex.Message };
                }
            }
        }

        #endregion

        #region 7. Apply Line Load

        public static object ApplyLineLoad(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int hostElementId = payload.GetProperty("host_element_id").GetInt32();
            var forceVector1 = payload.GetProperty("force_vector1");
            var forceVector2 = payload.GetProperty("force_vector2");

            XYZ force1 = new XYZ(
                forceVector1.GetProperty("x").GetDouble(),
                forceVector1.GetProperty("y").GetDouble(),
                forceVector1.GetProperty("z").GetDouble()
            );

            XYZ force2 = new XYZ(
                forceVector2.GetProperty("x").GetDouble(),
                forceVector2.GetProperty("y").GetDouble(),
                forceVector2.GetProperty("z").GetDouble()
            );

            using (var trans = new Transaction(doc, "Apply Line Load"))
            {
                trans.Start();

                try
                {
                    Element hostElement = doc.GetElement(new ElementId(hostElementId));
                    if (hostElement == null)
                    {
                        throw new Exception($"Host element {hostElementId} not found");
                    }

                    // Create line load
                    LineLoad lineLoad = LineLoad.Create(doc, new ElementId(hostElementId), force1, force2);

                    trans.Commit();

                    return new
                    {
                        success = true,
                        loadId = lineLoad.Id.IntegerValue,
                        hostElementId = hostElementId,
                        force1 = new { x = force1.X, y = force1.Y, z = force1.Z },
                        force2 = new { x = force2.X, y = force2.Y, z = force2.Z }
                    };
                }
                catch (Exception ex)
                {
                    return new { success = false, error = ex.Message };
                }
            }
        }

        #endregion

        #region 8. Get Analytical Model

        public static object GetAnalyticalModel(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int elementId = payload.GetProperty("element_id").GetInt32();

            Element element = doc.GetElement(new ElementId(elementId));
            if (element == null)
            {
                throw new Exception($"Element {elementId} not found");
            }

            try
            {
                AnalyticalModel analyticalModel = null;

                if (element is FamilyInstance fi)
                {
                    analyticalModel = fi.GetAnalyticalModel();
                }
                else if (element is Wall wall)
                {
                    analyticalModel = wall.GetAnalyticalModel();
                }
                else if (element is Floor floor)
                {
                    analyticalModel = floor.GetAnalyticalModel();
                }

                if (analyticalModel == null)
                {
                    return new { success = false, error = "Element does not have an analytical model" };
                }

                IList<Curve> curves = analyticalModel.GetCurves(AnalyticalCurveType.ActiveCurves);

                return new
                {
                    success = true,
                    elementId = elementId,
                    hasAnalyticalModel = true,
                    curveCount = curves?.Count ?? 0
                };
            }
            catch (Exception ex)
            {
                return new { success = false, error = ex.Message };
            }
        }

        #endregion

        #region Helper Methods

        private static List<Face> GetFaces(Element element)
        {
            var faces = new List<Face>();
            Options options = new Options();
            GeometryElement geomElem = element.get_Geometry(options);

            foreach (GeometryObject geomObj in geomElem)
            {
                if (geomObj is Solid solid)
                {
                    foreach (Face face in solid.Faces)
                    {
                        faces.Add(face);
                    }
                }
            }

            return faces;
        }

        #endregion
    }
}
