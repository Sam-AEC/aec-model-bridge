using System;
using System.Drawing;
using Rhino;
using Rhino.Commands;
using Rhino.Geometry;
using Rhino.DocObjects;

namespace RhinoBridge
{
    public class GenerateDiagridTowerCommand : Command
    {
        public GenerateDiagridTowerCommand() { Instance = this; }

        public static GenerateDiagridTowerCommand Instance { get; private set; }

        public override string EnglishName => "generate_diagrid_tower";

        protected override Result RunCommand(RhinoDoc doc, RunMode mode)
        {
            double scale = RhinoMath.UnitScale(UnitSystem.Meters, doc.ModelUnitSystem);

            double baseRad    = 22.0 * scale;
            double waistRad   = 14.0 * scale;
            double topRad     = 19.0 * scale;
            double height     = 180.0 * scale;
            int    uDivs      = 16;
            int    vDivs      = 28;
            double mullionW   = 0.15;
            double mullionD   = 0.30;
            double glassThick = 0.024;

            RhinoApp.WriteLine("Generating tower surface...");
            var surface = DiagridGenerator.GenerateTowerSurface(baseRad, waistRad, topRad, height);
            if (surface == null) { RhinoApp.WriteLine("Failed to generate surface."); return Result.Failure; }

            var face = surface.Faces[0];
            var pts  = DiagridGenerator.SampleGridPoints(face, uDivs, vDivs);

            RhinoApp.WriteLine("Computing diagrid topology...");
            var diagridLines = DiagridGenerator.GenerateDiagridLines(pts, uDivs, vDivs);

            RhinoApp.WriteLine("Sweeping mullion profiles...");
            var profile  = CurtainWallDetailer.CreateMullionCurve(mullionW, mullionD, scale);
            var mullions = CurtainWallDetailer.GenerateMullionSweeps(diagridLines, profile, face);

            RhinoApp.WriteLine("Generating volumetric glass panels...");
            var glassPanels = CurtainWallDetailer.GenerateGlassPanels(pts, face, uDivs, vDivs, glassThick, 0.12, 0.02, scale);

            // Materials
            var aluminumMat = new Material { Name = "DarkAnodizedAluminum" };
            aluminumMat.DiffuseColor       = Color.FromArgb(30, 32, 38);
            aluminumMat.SpecularColor      = Color.FromArgb(155, 160, 170);
            aluminumMat.Reflectivity       = 0.85;
            aluminumMat.FresnelReflections = true;
            int aluminumMatIdx = doc.Materials.Add(aluminumMat);

            var glassMat = new Material { Name = "ArchitecturalGlass" };
            glassMat.DiffuseColor       = Color.FromArgb(18, 75, 52);
            glassMat.Transparency       = 0.85;
            glassMat.Reflectivity       = 0.92;
            glassMat.FresnelReflections = true;
            glassMat.IndexOfRefraction  = 1.52;
            int glassMatIdx = doc.Materials.Add(glassMat);

            // Layers
            int mullionLayerIdx = GetOrCreateLayer(doc, "Mullions", Color.FromArgb(38, 40, 48));
            int glassLayerIdx   = GetOrCreateLayer(doc, "Glass",    Color.FromArgb(18, 75, 52));

            var mullionAttr = new ObjectAttributes
            {
                LayerIndex = mullionLayerIdx, MaterialIndex = aluminumMatIdx,
                MaterialSource = ObjectMaterialSource.MaterialFromObject
            };
            var glassAttr = new ObjectAttributes
            {
                LayerIndex = glassLayerIdx, MaterialIndex = glassMatIdx,
                MaterialSource = ObjectMaterialSource.MaterialFromObject
            };

            RhinoApp.WriteLine($"Baking {mullions.Count} mullion sweeps...");
            foreach (var m in mullions) doc.Objects.AddBrep(m, mullionAttr);

            RhinoApp.WriteLine($"Baking {glassPanels.Count} glass panels...");
            foreach (var g in glassPanels) doc.Objects.AddBrep(g, glassAttr);

            doc.Views.Redraw();
            RhinoApp.WriteLine("High-fidelity diagrid tower complete!");
            return Result.Success;
        }

        private static int GetOrCreateLayer(RhinoDoc doc, string name, Color color)
        {
            var existing = doc.Layers.FindName(name, -1);
            if (existing != null) return existing.Index;
            return doc.Layers.Add(new Layer { Name = name, Color = color });
        }
    }
}
