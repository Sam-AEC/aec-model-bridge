using System;
using System.Collections.Generic;
using Rhino.Geometry;

namespace RhinoBridge
{
    public static class CurtainWallDetailer
    {
        public static Curve CreateMullionCurve(double width = 0.15, double depth = 0.30, double scale = 1.0)
        {
            double hw = width * scale * 0.5;
            double d  = depth * scale;
            var rect = new Rectangle3d(Plane.WorldXY, new Interval(-hw, hw), new Interval(-d, 0.0));
            return rect.ToNurbsCurve();
        }

        public static List<Brep> GenerateMullionSweeps(
            List<Curve> lines, Curve profileCurve, BrepFace face, double tolerance = 0.001)
        {
            var sweeps = new List<Brep>();
            foreach (var line in lines)
            {
                if (!line.PerpendicularFrameAt(line.Domain.Min, out Plane startFrame))
                    continue;

                var midPt = line.PointAt(line.Domain.Mid);
                if (!face.ClosestPoint(midPt, out double cu, out double cv))
                {
                    var xf = Transform.PlaneToPlane(Plane.WorldXY, startFrame);
                    var pf = profileCurve.DuplicateCurve(); pf.Transform(xf);
                    var fb = Brep.CreateFromSweep(line, pf, true, tolerance);
                    if (fb != null) sweeps.AddRange(fb);
                    continue;
                }

                var surfNormal = face.NormalAt(cu, cv); surfNormal.Unitize();
                var tangent   = startFrame.ZAxis;

                double dot = surfNormal * tangent;
                var depthDir = new Vector3d(
                    surfNormal.X - dot * tangent.X,
                    surfNormal.Y - dot * tangent.Y,
                    surfNormal.Z - dot * tangent.Z);
                if (depthDir.IsZero || !depthDir.Unitize()) depthDir = startFrame.YAxis;

                var widthDir = Vector3d.CrossProduct(tangent, depthDir);
                if (widthDir.IsZero || !widthDir.Unitize()) widthDir = startFrame.XAxis;

                var sweepPlane = new Plane(startFrame.Origin, widthDir, depthDir);
                var xform = Transform.PlaneToPlane(Plane.WorldXY, sweepPlane);
                var oriented = profileCurve.DuplicateCurve(); oriented.Transform(xform);

                var result = Brep.CreateFromSweep(line, oriented, true, tolerance);
                if (result != null) sweeps.AddRange(result);
            }
            return sweeps;
        }

        // Glass strategy: each rectangular UV cell is divided into 4 triangles by the X of the
        // two crossing diagonal mullions. Each triangle has vertices at:
        //   - the X crossing point  (cell centre, where the two mullions intersect)
        //   - two adjacent UV grid corners  (where 4 mullions from neighbouring cells meet)
        //
        // The glass triangle is inset from all 3 vertices toward its own centroid so it clears
        // the mullion profile widths, then extruded inward along the surface normal.
        public static List<Brep> GenerateGlassPanels(
            Point3d[,] pts, BrepFace face, int uDivs, int vDivs,
            double thickness  = 0.024,
            double insetRatio = 0.12,   // pull each vertex 12 % toward triangle centroid
            double setback    = 0.020,
            double scale      = 1.0)
        {
            double tol = 0.001 * scale;
            var panels = new List<Brep>();

            for (int i = 0; i < uDivs; i++)
            {
                for (int j = 0; j < vDivs; j++)
                {
                    var p0 = pts[i,     j    ];  // bottom-left
                    var p1 = pts[i + 1, j    ];  // bottom-right
                    var p2 = pts[i + 1, j + 1]; // top-right
                    var p3 = pts[i,     j + 1]; // top-left

                    // Cell centre = where the two diagonal mullions cross
                    var cx = new Point3d(
                        (p0.X + p1.X + p2.X + p3.X) * 0.25,
                        (p0.Y + p1.Y + p2.Y + p3.Y) * 0.25,
                        (p0.Z + p1.Z + p2.Z + p3.Z) * 0.25);

                    // The X splits the cell into 4 triangles.
                    // Winding: counter-clockwise when viewed from outside.
                    var tris = new[]
                    {
                        new[] { p0, p1, cx },  // bottom
                        new[] { p1, p2, cx },  // right
                        new[] { p2, p3, cx },  // top
                        new[] { p3, p0, cx },  // left
                    };

                    foreach (var tri in tris)
                    {
                        var A = tri[0]; var B = tri[1]; var C = tri[2];

                        // Triangle centroid
                        var tc = new Point3d(
                            (A.X + B.X + C.X) / 3.0,
                            (A.Y + B.Y + C.Y) / 3.0,
                            (A.Z + B.Z + C.Z) / 3.0);

                        // Inset each vertex toward centroid to clear mullion profiles
                        var gA = tc + (A - tc) * (1.0 - insetRatio);
                        var gB = tc + (B - tc) * (1.0 - insetRatio);
                        var gC = tc + (C - tc) * (1.0 - insetRatio);

                        // Surface normal at centroid for setback + thickness direction
                        if (!face.ClosestPoint(tc, out double cu, out double cv)) continue;
                        var n = face.NormalAt(cu, cv);
                        if (!n.Unitize()) continue;

                        var push  = n * (-setback   * scale);
                        var thick = n * (-thickness * scale);

                        // Outer (front) triangle face — set back slightly behind mullion plane
                        var fA = gA + push; var fB = gB + push; var fC = gC + push;
                        // Inner (back) face — extruded by glass thickness
                        var bA = fA + thick; var bB = fB + thick; var bC = fC + thick;

                        // 5-face triangular prism
                        var front = NurbsSurface.CreateFromCorners(fA, fB, fC);        // outer face
                        var back  = NurbsSurface.CreateFromCorners(bA, bC, bB);        // inner face (reversed)
                        var s1    = NurbsSurface.CreateFromCorners(fA, fB, bB, bA);   // side A-B
                        var s2    = NurbsSurface.CreateFromCorners(fB, fC, bC, bB);   // side B-C
                        var s3    = NurbsSurface.CreateFromCorners(fC, fA, bA, bC);   // side C-A

                        var faces = new List<Brep>();
                        foreach (var ns in new[] { front, back, s1, s2, s3 })
                            if (ns != null) faces.Add(ns.ToBrep());

                        if (faces.Count < 5) continue;

                        var joined = Brep.JoinBreps(faces, tol);
                        if (joined != null && joined.Length > 0)
                            panels.Add(joined[0]);
                        else
                            panels.AddRange(faces);
                    }
                }
            }
            return panels;
        }
    }
}
