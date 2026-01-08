using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Architecture;
using Autodesk.Revit.UI;

namespace RevitBridge.Commands.Specialized.Stairs
{
    /// <summary>
    /// Stairs and railing commands for circulation design
    /// Stairs (#539, Score: 133), StairsRun (#540, Score: 133), Railing (#541, Score: 133)
    /// </summary>
    public static class StairsCommands
    {
        #region 1. Create Stairs by Sketch

        public static object CreateStairsBySketch(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int baseLevelId = payload.GetProperty("base_level_id").GetInt32();
            int topLevelId = payload.GetProperty("top_level_id").GetInt32();
            int stairsTypeId = payload.GetProperty("stairs_type_id").GetInt32();

            using (var trans = new Transaction(doc, "Create Stairs by Sketch"))
            {
                trans.Start();

                try
                {
                    Level baseLevel = doc.GetElement(new ElementId(baseLevelId)) as Level;
                    Level topLevel = doc.GetElement(new ElementId(topLevelId)) as Level;
                    StairsType stairsType = doc.GetElement(new ElementId(stairsTypeId)) as StairsType;

                    if (baseLevel == null || topLevel == null || stairsType == null)
                    {
                        throw new Exception("Base level, top level, or stairs type not found");
                    }

                    // Create stairs edit scope
                    StairsEditScope stairsEdit = doc.Create.NewStairsEditScope();

                    // Note: Actual sketch creation requires user interaction in Revit UI
                    // This is a template that would need to be completed with actual sketch curves

                    Stairs stairs = stairsEdit.CommitStairs(doc);

                    trans.Commit();

                    return new
                    {
                        success = true,
                        stairsId = stairs.Id.IntegerValue,
                        baseLevelId = baseLevelId,
                        topLevelId = topLevelId,
                        message = "Stairs sketch mode started - requires manual sketch completion"
                    };
                }
                catch (Exception ex)
                {
                    return new { success = false, error = ex.Message };
                }
            }
        }

        #endregion

        #region 2. Create Railing

        public static object CreateRailing(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int hostElementId = payload.GetProperty("host_element_id").GetInt32();
            int railingTypeId = payload.GetProperty("railing_type_id").GetInt32();

            using (var trans = new Transaction(doc, "Create Railing"))
            {
                trans.Start();

                try
                {
                    Element hostElement = doc.GetElement(new ElementId(hostElementId));
                    RailingType railingType = doc.GetElement(new ElementId(railingTypeId)) as RailingType;

                    if (hostElement == null || railingType == null)
                    {
                        throw new Exception("Host element or railing type not found");
                    }

                    // Get path from host (stairs, ramp, or floor/roof)
                    Railing railing = null;

                    if (hostElement is Stairs stairs)
                    {
                        // Create railing on stairs
                        ICollection<ElementId> stairsRuns = stairs.GetStairsRuns();
                        if (stairsRuns.Count > 0)
                        {
                            StairsRun run = doc.GetElement(stairsRuns.First()) as StairsRun;
                            if (run != null)
                            {
                                CurveLoop path = run.GetStairsPath();
                                List<Curve> curves = path.ToList();

                                if (curves.Count > 0)
                                {
                                    railing = Railing.Create(doc, curves, railingType.Id, hostElement.LevelId);
                                }
                            }
                        }
                    }

                    trans.Commit();

                    if (railing != null)
                    {
                        return new
                        {
                            success = true,
                            railingId = railing.Id.IntegerValue,
                            hostElementId = hostElementId,
                            railingTypeName = railingType.Name
                        };
                    }
                    else
                    {
                        return new { success = false, error = "Failed to create railing" };
                    }
                }
                catch (Exception ex)
                {
                    return new { success = false, error = ex.Message };
                }
            }
        }

        #endregion

        #region 3. Set Stairs Path

        public static object SetStairsPath(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int stairsId = payload.GetProperty("stairs_id").GetInt32();
            var pathPoints = payload.GetProperty("path_points").EnumerateArray();

            using (var trans = new Transaction(doc, "Set Stairs Path"))
            {
                trans.Start();

                try
                {
                    Stairs stairs = doc.GetElement(new ElementId(stairsId)) as Stairs;
                    if (stairs == null)
                    {
                        throw new Exception($"Stairs {stairsId} not found");
                    }

                    // Convert JSON points to XYZ
                    List<XYZ> points = new List<XYZ>();
                    foreach (var point in pathPoints)
                    {
                        points.Add(new XYZ(
                            point.GetProperty("x").GetDouble(),
                            point.GetProperty("y").GetDouble(),
                            point.GetProperty("z").GetDouble()
                        ));
                    }

                    // Create curves from points
                    List<Curve> curves = new List<Curve>();
                    for (int i = 0; i < points.Count - 1; i++)
                    {
                        curves.Add(Line.CreateBound(points[i], points[i + 1]));
                    }

                    // Note: Modifying existing stairs path requires StairsEditScope
                    // This is a template implementation

                    trans.Commit();

                    return new
                    {
                        success = true,
                        stairsId = stairsId,
                        pathPointCount = points.Count,
                        message = "Stairs path modification requires StairsEditScope"
                    };
                }
                catch (Exception ex)
                {
                    return new { success = false, error = ex.Message };
                }
            }
        }

        #endregion

        #region 4. Modify Stairs Run

        public static object ModifyStairsRun(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int stairsRunId = payload.GetProperty("stairs_run_id").GetInt32();
            int? numberOfRisers = payload.TryGetProperty("number_of_risers", out var nr) ? nr.GetInt32() : null;
            double? runWidth = payload.TryGetProperty("run_width", out var rw) ? rw.GetDouble() : null;

            using (var trans = new Transaction(doc, "Modify Stairs Run"))
            {
                trans.Start();

                try
                {
                    StairsRun stairsRun = doc.GetElement(new ElementId(stairsRunId)) as StairsRun;
                    if (stairsRun == null)
                    {
                        throw new Exception($"Stairs run {stairsRunId} not found");
                    }

                    // Set number of risers
                    if (numberOfRisers.HasValue)
                    {
                        Parameter risersParam = stairsRun.get_Parameter(BuiltInParameter.STAIRS_ACTUAL_NUM_RISERS);
                        if (risersParam != null && !risersParam.IsReadOnly)
                        {
                            risersParam.Set(numberOfRisers.Value);
                        }
                    }

                    // Set run width
                    if (runWidth.HasValue)
                    {
                        Parameter widthParam = stairsRun.get_Parameter(BuiltInParameter.STAIRS_ATTR_RUN_WIDTH);
                        if (widthParam != null && !widthParam.IsReadOnly)
                        {
                            widthParam.Set(runWidth.Value);
                        }
                    }

                    trans.Commit();

                    return new
                    {
                        success = true,
                        stairsRunId = stairsRunId,
                        numberOfRisers = numberOfRisers,
                        runWidth = runWidth
                    };
                }
                catch (Exception ex)
                {
                    return new { success = false, error = ex.Message };
                }
            }
        }

        #endregion

        #region 5. Get Stairs Info

        public static object GetStairsInfo(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int stairsId = payload.GetProperty("stairs_id").GetInt32();

            Stairs stairs = doc.GetElement(new ElementId(stairsId)) as Stairs;
            if (stairs == null)
            {
                throw new Exception($"Stairs {stairsId} not found");
            }

            try
            {
                ICollection<ElementId> stairsRuns = stairs.GetStairsRuns();
                ICollection<ElementId> stairsLandings = stairs.GetStairsLandings();
                ICollection<ElementId> stairsSupports = stairs.GetStairsSupports();

                var runsInfo = new List<object>();
                foreach (var runId in stairsRuns)
                {
                    StairsRun run = doc.GetElement(runId) as StairsRun;
                    if (run != null)
                    {
                        runsInfo.Add(new
                        {
                            runId = run.Id.IntegerValue,
                            numberOfRisers = run.ActualRisersNumber,
                            numberOfTreads = run.ActualTreadsNumber,
                            height = run.Height,
                            width = run.ActualRunWidth
                        });
                    }
                }

                return new
                {
                    success = true,
                    stairsId = stairsId,
                    stairsName = stairs.Name,
                    numberOfRuns = stairsRuns.Count,
                    numberOfLandings = stairsLandings.Count,
                    numberOfSupports = stairsSupports.Count,
                    runs = runsInfo,
                    baseLevelId = stairs.get_Parameter(BuiltInParameter.STAIRS_BASE_LEVEL_PARAM)?.AsElementId().IntegerValue,
                    topLevelId = stairs.get_Parameter(BuiltInParameter.STAIRS_TOP_LEVEL_PARAM)?.AsElementId().IntegerValue
                };
            }
            catch (Exception ex)
            {
                return new { success = false, error = ex.Message };
            }
        }

        #endregion

        #region 6. Get Railing Info

        public static object GetRailingInfo(UIApplication app, JsonElement payload)
        {
            var doc = app.ActiveUIDocument.Document;
            int railingId = payload.GetProperty("railing_id").GetInt32();

            Railing railing = doc.GetElement(new ElementId(railingId)) as Railing;
            if (railing == null)
            {
                throw new Exception($"Railing {railingId} not found");
            }

            try
            {
                // Get railing path
                CurveLoop path = railing.GetPath();
                double pathLength = 0;
                int curveCount = 0;

                foreach (Curve curve in path)
                {
                    pathLength += curve.Length;
                    curveCount++;
                }

                // Get host element
                ElementId hostId = railing.HostId;
                Element hostElement = hostId != ElementId.InvalidElementId ? doc.GetElement(hostId) : null;

                return new
                {
                    success = true,
                    railingId = railingId,
                    railingName = railing.Name,
                    pathLength = pathLength,
                    pathCurveCount = curveCount,
                    hostElementId = hostElement?.Id.IntegerValue,
                    hostElementType = hostElement?.GetType().Name,
                    levelId = railing.get_Parameter(BuiltInParameter.STAIRS_RAILING_BASE_LEVEL_PARAM)?.AsElementId().IntegerValue
                };
            }
            catch (Exception ex)
            {
                return new { success = false, error = ex.Message };
            }
        }

        #endregion
    }
}
