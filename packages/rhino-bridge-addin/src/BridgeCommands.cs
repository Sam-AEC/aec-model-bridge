using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;

namespace RhinoBridge
{
    public static class BridgeCommands
    {
        public static string ExecuteCommand(string jsonPayload)
        {
            try
            {
                using var doc = JsonDocument.Parse(jsonPayload);
                var root = doc.RootElement;
                if (!root.TryGetProperty("command", out var commandElement))
                    return JsonSerializer.Serialize(new { error = "Missing 'command' property in request." });

                var command = commandElement.GetString();
                var activeDoc = RhinoDoc.ActiveDoc;
                if (activeDoc == null)
                    return JsonSerializer.Serialize(new { error = "No active Rhino document." });

                switch (command)
                {
                    case "get_document_info":
                        return JsonSerializer.Serialize(new
                        {
                            success = true,
                            data = new
                            {
                                name = activeDoc.Name,
                                path = activeDoc.Path,
                                modelUnitSystem = activeDoc.ModelUnitSystem.ToString(),
                                objectCount = activeDoc.Objects.Count()
                            }
                        });

                    case "get_lines":
                        var lines = activeDoc.Objects
                            .Where(o => o.Geometry is Rhino.Geometry.Curve)
                            .Select(o => {
                                var crv = (Rhino.Geometry.Curve)o.Geometry;
                                return new {
                                    start = new { x = crv.PointAtStart.X, y = crv.PointAtStart.Y, z = crv.PointAtStart.Z },
                                    end   = new { x = crv.PointAtEnd.X,   y = crv.PointAtEnd.Y,   z = crv.PointAtEnd.Z   }
                                };
                            }).ToList();
                        return JsonSerializer.Serialize(new { success = true, data = lines });

                    case "invoke_method":
                    {
                        var className  = root.GetProperty("class_name").GetString();
                        var methodName = root.GetProperty("method_name").GetString();
                        var args       = root.GetProperty("arguments");
                        var targetId   = root.TryGetProperty("target_id", out var tId) ? tId.GetString() : null;
                        var result     = ReflectionHelper.InvokeMethod(activeDoc, className, methodName, args, targetId);
                        return JsonSerializer.Serialize(new { success = true, data = result });
                    }

                    case "reflect_get":
                    {
                        var targetId     = root.GetProperty("target_id").GetString();
                        var propertyName = root.GetProperty("property_name").GetString();
                        var target       = ReflectionHelper.GetObject(targetId, activeDoc);
                        if (target == null) throw new Exception($"Target '{targetId}' not found");
                        var prop  = target.GetType().GetProperty(propertyName)
                                    ?? throw new Exception($"Property '{propertyName}' not found on '{target.GetType().Name}'");
                        var value = prop.GetValue(target);
                        if (value == null) return JsonSerializer.Serialize(new { success = true, data = (object)null });
                        if (value.GetType().IsPrimitive || value is string) return JsonSerializer.Serialize(new { success = true, data = value });
                        if (value is Guid g) return JsonSerializer.Serialize(new { success = true, data = g.ToString() });
                        var refId = ReflectionHelper.RegisterObject(value);
                        return JsonSerializer.Serialize(new { success = true, data = new { type = "reference", id = refId, class_name = value.GetType().Name, str = value.ToString() } });
                    }

                    case "reflect_set":
                    {
                        var targetId     = root.GetProperty("target_id").GetString();
                        var propertyName = root.GetProperty("property_name").GetString();
                        var valueElement = root.GetProperty("value");
                        var target       = ReflectionHelper.GetObject(targetId, activeDoc)
                                           ?? throw new Exception($"Target '{targetId}' not found");
                        var prop         = target.GetType().GetProperty(propertyName)
                                           ?? throw new Exception($"Property '{propertyName}' not found on '{target.GetType().Name}'");
                        var value        = ReflectionHelper.ParseArgument(valueElement, activeDoc);
                        if (value != null && !prop.PropertyType.IsAssignableFrom(value.GetType()))
                            value = Convert.ChangeType(value, prop.PropertyType);
                        prop.SetValue(target, value);
                        return JsonSerializer.Serialize(new { success = true, data = new { status = "success", target_id = targetId, property = propertyName } });
                    }

                    // Executes arbitrary Python code inside Rhino's IronPython engine.
                    // All geometry written in the Python code runs with full RhinoCommon access.
                    case "run_python":
                    {
                        var code = root.GetProperty("code").GetString()
                                   ?? throw new Exception("Missing 'code' property");

                        var outputSb = new StringBuilder();

                        // IronPython via Rhino.Runtime.PythonScript (Rhino 6/7/8)
                        var python = Rhino.Runtime.PythonScript.Create();
                        if (python != null)
                        {
                            python.Output += s => outputSb.Append(s);
                            python.ExecuteScript(code);
                            activeDoc.Views.Redraw();
                            return JsonSerializer.Serialize(new { success = true, output = outputSb.ToString() });
                        }

                        // Fallback: write temp .py file and invoke Rhino command
                        var tmp = Path.Combine(Path.GetTempPath(), $"rh_{Guid.NewGuid():N}.py");
                        File.WriteAllText(tmp, code, Encoding.UTF8);
                        try
                        {
                            RhinoApp.RunScript($"_RunPythonScript \"{tmp}\"", false);
                            activeDoc.Views.Redraw();
                            return JsonSerializer.Serialize(new { success = true, output = "Script executed (file mode)" });
                        }
                        finally { try { File.Delete(tmp); } catch { } }
                    }

                    case "generate_diagrid_tower":
                    {
                        double scale = RhinoMath.UnitScale(UnitSystem.Meters, activeDoc.ModelUnitSystem);

                        double baseRad      = (root.TryGetProperty("base_radius",      out var br) ? br.GetDouble() : 22.0) * scale;
                        double waistRad     = (root.TryGetProperty("waist_radius",     out var wr) ? wr.GetDouble() : 14.0) * scale;
                        double topRad       = (root.TryGetProperty("top_radius",       out var tr) ? tr.GetDouble() : 19.0) * scale;
                        double height       = (root.TryGetProperty("height",           out var h)  ? h.GetDouble()  : 180.0) * scale;
                        int    uDivs        = root.TryGetProperty("u_divs",            out var u)  ? u.GetInt32()   : 16;
                        int    vDivs        = root.TryGetProperty("v_divs",            out var v)  ? v.GetInt32()   : 28;
                        double mullionW     = root.TryGetProperty("mullion_width",     out var mw) ? mw.GetDouble() : 0.15;
                        double mullionD     = root.TryGetProperty("mullion_depth",     out var md) ? md.GetDouble() : 0.30;
                        double glassThick   = root.TryGetProperty("glass_thickness",   out var gt) ? gt.GetDouble() : 0.024;
                        double insetRatio   = root.TryGetProperty("inset_ratio",       out var ir) ? ir.GetDouble() : 0.12;

                        // --- Geometry ---
                        var surface = DiagridGenerator.GenerateTowerSurface(baseRad, waistRad, topRad, height);
                        if (surface == null) throw new Exception("Failed to generate tower surface.");

                        var face         = surface.Faces[0];
                        var pts          = DiagridGenerator.SampleGridPoints(face, uDivs, vDivs);
                        var diagridLines = DiagridGenerator.GenerateDiagridLines(pts, uDivs, vDivs);

                        var profile     = CurtainWallDetailer.CreateMullionCurve(mullionW, mullionD, scale);
                        var mullions    = CurtainWallDetailer.GenerateMullionSweeps(diagridLines, profile, face);
                        var glassPanels = CurtainWallDetailer.GenerateGlassPanels(pts, face, uDivs, vDivs, glassThick, insetRatio, 0.02, scale);

                        // --- PBR Materials ---
                        int mullionMatIdx = CreateAluminumMaterial(activeDoc);
                        int glassMatIdx   = CreateGlassMaterial(activeDoc);

                        // --- Layers ---
                        int mullionLayer = GetOrCreateLayer(activeDoc, "Mullions", Color.FromArgb(38, 40, 48));
                        int glassLayer   = GetOrCreateLayer(activeDoc, "Glass",    Color.FromArgb(18, 75, 52));

                        var mullionAttr = new ObjectAttributes
                        {
                            LayerIndex     = mullionLayer,
                            MaterialIndex  = mullionMatIdx,
                            MaterialSource = ObjectMaterialSource.MaterialFromObject
                        };
                        var glassAttr = new ObjectAttributes
                        {
                            LayerIndex     = glassLayer,
                            MaterialIndex  = glassMatIdx,
                            MaterialSource = ObjectMaterialSource.MaterialFromObject
                        };

                        // --- Bake ---
                        int mullionCount = 0;
                        foreach (var m in mullions) { activeDoc.Objects.AddBrep(m, mullionAttr); mullionCount++; }

                        int glassCount = 0;
                        foreach (var g in glassPanels) { activeDoc.Objects.AddBrep(g, glassAttr); glassCount++; }

                        activeDoc.Views.Redraw();

                        return JsonSerializer.Serialize(new
                        {
                            success = true,
                            data = new
                            {
                                message = $"Generated {mullionCount} mullion sweeps and {glassCount} glass solids with PBR materials.",
                                mullionCount,
                                glassCount
                            }
                        });
                    }

                    // ── God Mode commands ─────────────────────────────────────────────────

                    case "get_scene":
                    {
                        var objects = activeDoc.Objects.Select(o => {
                            var bb = o.Geometry.GetBoundingBox(false);
                            return new {
                                id      = o.Id.ToString(),
                                type    = o.Geometry.GetType().Name,
                                layer   = activeDoc.Layers[o.Attributes.LayerIndex].Name,
                                bbox    = new {
                                    min = new { x = bb.Min.X, y = bb.Min.Y, z = bb.Min.Z },
                                    max = new { x = bb.Max.X, y = bb.Max.Y, z = bb.Max.Z }
                                }
                            };
                        }).ToList();
                        return JsonSerializer.Serialize(new { success = true, data = objects });
                    }

                    case "list_layers":
                    {
                        var layers = activeDoc.Layers.Select(l => new {
                            name    = l.Name,
                            color   = new { r = l.Color.R, g = l.Color.G, b = l.Color.B },
                            visible = l.IsVisible,
                            locked  = l.IsLocked
                        }).ToList();
                        return JsonSerializer.Serialize(new { success = true, data = layers });
                    }

                    case "clear_scene":
                    {
                        int deleted = 0;
                        if (root.TryGetProperty("layer", out var layerEl))
                        {
                            var layerName = layerEl.GetString();
                            var li = activeDoc.Layers.FindName(layerName, -1);
                            if (li == null) throw new Exception($"Layer '{layerName}' not found");
                            var ids = activeDoc.Objects
                                .Where(o => o.Attributes.LayerIndex == li.Index)
                                .Select(o => o.Id).ToList();
                            foreach (var id in ids) { activeDoc.Objects.Delete(id, true); deleted++; }
                        }
                        else
                        {
                            var ids = activeDoc.Objects.Select(o => o.Id).ToList();
                            foreach (var id in ids) { activeDoc.Objects.Delete(id, true); deleted++; }
                        }
                        activeDoc.Views.Redraw();
                        return JsonSerializer.Serialize(new { success = true, data = new { deleted } });
                    }

                    case "set_view":
                    {
                        var view = root.TryGetProperty("view", out var vEl) ? vEl.GetString() : "perspective";
                        var vp = activeDoc.Views.ActiveView?.ActiveViewport;
                        if (vp == null) throw new Exception("No active viewport");

                        switch (view.ToLower())
                        {
                            case "top":
                                vp.SetCameraLocations(new Point3d(0, 0, 100), new Point3d(0, 0, 0));
                                vp.CameraUp = Vector3d.YAxis;
                                vp.ChangeToParallelProjection(true);
                                break;
                            case "front":
                                vp.SetCameraLocations(new Point3d(0, -100, 0), new Point3d(0, 0, 0));
                                vp.CameraUp = Vector3d.ZAxis;
                                vp.ChangeToParallelProjection(true);
                                break;
                            case "right":
                                vp.SetCameraLocations(new Point3d(100, 0, 0), new Point3d(0, 0, 0));
                                vp.CameraUp = Vector3d.ZAxis;
                                vp.ChangeToParallelProjection(true);
                                break;
                            case "perspective":
                            default:
                                vp.ChangeToPerspectiveProjection(true, 50);
                                break;
                            case "rendered":
                                RhinoApp.RunScript("_SetDisplayMode _Rendered", false);
                                break;
                            case "arctic":
                                RhinoApp.RunScript("_SetDisplayMode _Arctic", false);
                                break;
                        }
                        activeDoc.Views.Redraw();
                        return JsonSerializer.Serialize(new { success = true, data = new { view } });
                    }

                    case "create_box":
                    {
                        double sc = RhinoMath.UnitScale(UnitSystem.Meters, activeDoc.ModelUnitSystem);
                        var minArr = root.GetProperty("min_pt");
                        var maxArr = root.GetProperty("max_pt");
                        var min = new Point3d(minArr[0].GetDouble() * sc, minArr[1].GetDouble() * sc, minArr[2].GetDouble() * sc);
                        var max = new Point3d(maxArr[0].GetDouble() * sc, maxArr[1].GetDouble() * sc, maxArr[2].GetDouble() * sc);
                        var box = new Box(new BoundingBox(min, max));
                        var brep = box.ToBrep();
                        var attr = BuildAttr(root, activeDoc);
                        var id = activeDoc.Objects.AddBrep(brep, attr);
                        activeDoc.Views.Redraw();
                        return JsonSerializer.Serialize(new { success = true, data = new { id = id.ToString() } });
                    }

                    case "create_sphere":
                    {
                        double sc = RhinoMath.UnitScale(UnitSystem.Meters, activeDoc.ModelUnitSystem);
                        var cArr = root.GetProperty("center");
                        var center = new Point3d(cArr[0].GetDouble() * sc, cArr[1].GetDouble() * sc, cArr[2].GetDouble() * sc);
                        double radius = root.GetProperty("radius").GetDouble() * sc;
                        var sphere = new Sphere(center, radius);
                        var attr = BuildAttr(root, activeDoc);
                        var id = activeDoc.Objects.AddBrep(sphere.ToBrep(), attr);
                        activeDoc.Views.Redraw();
                        return JsonSerializer.Serialize(new { success = true, data = new { id = id.ToString() } });
                    }

                    case "create_cylinder":
                    {
                        double sc = RhinoMath.UnitScale(UnitSystem.Meters, activeDoc.ModelUnitSystem);
                        var bArr = root.GetProperty("base");
                        var basePt = new Point3d(bArr[0].GetDouble() * sc, bArr[1].GetDouble() * sc, bArr[2].GetDouble() * sc);
                        double height = root.GetProperty("height").GetDouble() * sc;
                        double radius = root.GetProperty("radius").GetDouble() * sc;
                        var circle = new Circle(new Plane(basePt, Vector3d.ZAxis), radius);
                        var cyl = new Cylinder(circle, height);
                        var attr = BuildAttr(root, activeDoc);
                        var id = activeDoc.Objects.AddBrep(cyl.ToBrep(true, true), attr);
                        activeDoc.Views.Redraw();
                        return JsonSerializer.Serialize(new { success = true, data = new { id = id.ToString() } });
                    }

                    case "boolean_union":
                    {
                        var idsEl = root.GetProperty("ids");
                        var breps = new List<Brep>();
                        foreach (var idEl in idsEl.EnumerateArray())
                        {
                            var obj = activeDoc.Objects.FindId(Guid.Parse(idEl.GetString()));
                            if (obj?.Geometry is Brep b) breps.Add(b);
                        }
                        var results = Brep.CreateBooleanUnion(breps, activeDoc.ModelAbsoluteTolerance);
                        if (results == null || results.Length == 0) throw new Exception("Boolean union failed");
                        var attr = BuildAttr(root, activeDoc);
                        var resultIds = results.Select(r => activeDoc.Objects.AddBrep(r, attr).ToString()).ToList();
                        // Remove inputs
                        foreach (var idEl in root.GetProperty("ids").EnumerateArray())
                            activeDoc.Objects.Delete(Guid.Parse(idEl.GetString()), true);
                        activeDoc.Views.Redraw();
                        return JsonSerializer.Serialize(new { success = true, data = new { ids = resultIds } });
                    }

                    case "boolean_difference":
                    {
                        var baseObj = activeDoc.Objects.FindId(Guid.Parse(root.GetProperty("base_id").GetString()));
                        if (baseObj?.Geometry is not Brep baseBrep) throw new Exception("base_id not a Brep");
                        var cutters = new List<Brep>();
                        foreach (var idEl in root.GetProperty("cutter_ids").EnumerateArray())
                        {
                            var obj = activeDoc.Objects.FindId(Guid.Parse(idEl.GetString()));
                            if (obj?.Geometry is Brep b) cutters.Add(b);
                        }
                        var results = Brep.CreateBooleanDifference(
                            new[] { baseBrep }, cutters, activeDoc.ModelAbsoluteTolerance);
                        if (results == null || results.Length == 0) throw new Exception("Boolean difference failed");
                        var attr = BuildAttr(root, activeDoc);
                        var resultIds = results.Select(r => activeDoc.Objects.AddBrep(r, attr).ToString()).ToList();
                        activeDoc.Objects.Delete(baseObj.Id, true);
                        foreach (var idEl in root.GetProperty("cutter_ids").EnumerateArray())
                            activeDoc.Objects.Delete(Guid.Parse(idEl.GetString()), true);
                        activeDoc.Views.Redraw();
                        return JsonSerializer.Serialize(new { success = true, data = new { ids = resultIds } });
                    }

                    case "set_material":
                    {
                        var mat = new Material();
                        if (root.TryGetProperty("name", out var nameEl)) mat.Name = nameEl.GetString();
                        if (root.TryGetProperty("color", out var colorEl))
                            mat.DiffuseColor = Color.FromArgb(colorEl[0].GetInt32(), colorEl[1].GetInt32(), colorEl[2].GetInt32());
                        if (root.TryGetProperty("transparency", out var transEl)) mat.Transparency = transEl.GetDouble();
                        if (root.TryGetProperty("reflectivity", out var reflEl))  mat.Reflectivity  = reflEl.GetDouble();
                        mat.FresnelReflections = true;
                        int matIdx = activeDoc.Materials.Add(mat);

                        var objAttr = new ObjectAttributes
                        {
                            MaterialIndex  = matIdx,
                            MaterialSource = ObjectMaterialSource.MaterialFromObject
                        };

                        var targets = new List<Guid>();
                        if (root.TryGetProperty("ids", out var idsEl2))
                            foreach (var idEl in idsEl2.EnumerateArray())
                                targets.Add(Guid.Parse(idEl.GetString()));
                        else if (root.TryGetProperty("layer", out var lEl2))
                        {
                            var li = activeDoc.Layers.FindName(lEl2.GetString(), -1);
                            if (li != null)
                                targets.AddRange(activeDoc.Objects
                                    .Where(o => o.Attributes.LayerIndex == li.Index)
                                    .Select(o => o.Id));
                        }

                        int changed = 0;
                        foreach (var id in targets)
                        {
                            var obj = activeDoc.Objects.FindId(id);
                            if (obj == null) continue;
                            var a = obj.Attributes.Duplicate();
                            a.MaterialIndex  = matIdx;
                            a.MaterialSource = ObjectMaterialSource.MaterialFromObject;
                            activeDoc.Objects.ModifyAttributes(obj, a, true);
                            changed++;
                        }
                        activeDoc.Views.Redraw();
                        return JsonSerializer.Serialize(new { success = true, data = new { changed, materialIndex = matIdx } });
                    }

                    case "transform_objects":
                    {
                        var ids = root.GetProperty("ids").EnumerateArray()
                            .Select(e => Guid.Parse(e.GetString())).ToList();
                        double sc = RhinoMath.UnitScale(UnitSystem.Meters, activeDoc.ModelUnitSystem);

                        Transform xform = Transform.Identity;
                        if (root.TryGetProperty("translation", out var tEl))
                        {
                            xform = Transform.Translation(
                                tEl[0].GetDouble() * sc,
                                tEl[1].GetDouble() * sc,
                                tEl[2].GetDouble() * sc);
                        }
                        else if (root.TryGetProperty("rotation", out var rEl))
                        {
                            var axis   = new Vector3d(rEl.GetProperty("axis")[0].GetDouble(),
                                                      rEl.GetProperty("axis")[1].GetDouble(),
                                                      rEl.GetProperty("axis")[2].GetDouble());
                            double deg = rEl.GetProperty("angle_deg").GetDouble();
                            Point3d origin = Point3d.Origin;
                            if (rEl.TryGetProperty("origin", out var oEl))
                                origin = new Point3d(oEl[0].GetDouble() * sc, oEl[1].GetDouble() * sc, oEl[2].GetDouble() * sc);
                            xform = Transform.Rotation(RhinoMath.ToRadians(deg), axis, origin);
                        }
                        else if (root.TryGetProperty("scale", out var sEl))
                        {
                            xform = Transform.Scale(Point3d.Origin,
                                (sEl[0].GetDouble() + sEl[1].GetDouble() + sEl[2].GetDouble()) / 3.0);
                        }

                        int moved = 0;
                        foreach (var id in ids)
                        {
                            if (activeDoc.Objects.Transform(id, xform, true) != Guid.Empty) moved++;
                        }
                        activeDoc.Views.Redraw();
                        return JsonSerializer.Serialize(new { success = true, data = new { moved } });
                    }

                    default:
                        return JsonSerializer.Serialize(new { error = $"Unknown command: {command}" });
                }
            }
            catch (Exception ex)
            {
                return JsonSerializer.Serialize(new { error = ex.Message, stackTrace = ex.StackTrace });
            }
        }

        // ── Material helpers ──────────────────────────────────────────────────────

        private static int CreateAluminumMaterial(RhinoDoc doc)
        {
            var mat = new Material { Name = "DarkAnodizedAluminum" };
            try
            {
                mat.ToPhysicallyBased(); // void in Rhino 7, bool in Rhino 8 — just call it
                var pbr = mat.PhysicallyBased;
                pbr.BaseColor = new Rhino.Display.Color4f(0.035f, 0.038f, 0.046f, 1.0f);
                pbr.Metallic  = 0.95;
                pbr.Roughness = 0.22;
                // "Reflectance" in Rhino 8, "Specular" in Rhino 7 — try both via reflection
                SetPbrProperty(pbr, 0.85, "Reflectance", "Specular");
            }
            catch { /* no PBR support in this build — standard props used below */ }

            // Standard props: always set so the material looks correct in all display modes
            mat.DiffuseColor       = Color.FromArgb(30, 32, 38);
            mat.SpecularColor      = Color.FromArgb(155, 160, 170);
            mat.Reflectivity       = 0.85;
            mat.FresnelReflections = true;
            mat.Shine              = (int)(0.65 * Material.MaxShine);
            return doc.Materials.Add(mat);
        }

        private static int CreateGlassMaterial(RhinoDoc doc)
        {
            var mat = new Material { Name = "ArchitecturalGlass_PBR" };
            try
            {
                mat.ToPhysicallyBased();
                var pbr = mat.PhysicallyBased;
                pbr.BaseColor = new Rhino.Display.Color4f(0.030f, 0.160f, 0.090f, 1.0f);
                pbr.Metallic  = 0.0;
                pbr.Roughness = 0.02;
                pbr.Opacity   = 0.12;   // 88% transparent
                SetPbrProperty(pbr, 0.92, "Reflectance", "Specular");
                SetPbrProperty(pbr, 1.52, "OpacityIOR"); // Rhino 8+ only; silently skipped on Rhino 7
            }
            catch { /* fall through */ }

            // Standard fallback properties — always set for Shaded/Arctic/non-PBR display modes
            mat.DiffuseColor       = Color.FromArgb(18, 75, 52);
            mat.Transparency       = 0.85;
            mat.Reflectivity       = 0.92;
            mat.FresnelReflections = true;
            mat.IndexOfRefraction  = 1.52;
            return doc.Materials.Add(mat);
        }

        // Tries each candidate property name in order; silently ignores missing ones.
        // Using reflection means we compile against Rhino 7 SDK but benefit from Rhino 8 PBR props at runtime.
        private static void SetPbrProperty(object pbr, object value, params string[] candidateNames)
        {
            foreach (var name in candidateNames)
            {
                try
                {
                    var prop = pbr.GetType().GetProperty(name);
                    if (prop == null) continue;
                    // PhysicallyBasedMaterial is a class, so SetValue modifies the actual instance
                    prop.SetValue(pbr, Convert.ChangeType(value, prop.PropertyType));
                    return;
                }
                catch { }
            }
        }

        private static int GetOrCreateLayer(RhinoDoc doc, string name, Color color)
        {
            var existing = doc.Layers.FindName(name, -1);
            if (existing != null) return existing.Index;
            var layer = new Layer { Name = name, Color = color };
            return doc.Layers.Add(layer);
        }

        // Builds ObjectAttributes from optional "layer" and "color" keys in the request.
        private static ObjectAttributes BuildAttr(JsonElement root, RhinoDoc doc)
        {
            var attr = new ObjectAttributes();
            if (root.TryGetProperty("layer", out var lEl))
                attr.LayerIndex = GetOrCreateLayer(doc, lEl.GetString(), Color.White);
            if (root.TryGetProperty("color", out var cEl))
            {
                var mat = new Material
                {
                    DiffuseColor = Color.FromArgb(cEl[0].GetInt32(), cEl[1].GetInt32(), cEl[2].GetInt32())
                };
                attr.MaterialIndex  = doc.Materials.Add(mat);
                attr.MaterialSource = ObjectMaterialSource.MaterialFromObject;
            }
            return attr;
        }
    }
}
