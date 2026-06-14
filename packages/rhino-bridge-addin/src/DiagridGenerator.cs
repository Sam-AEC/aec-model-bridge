using System;
using System.Collections.Generic;
using Rhino.Geometry;

namespace RhinoBridge
{
    public static class DiagridGenerator
    {
        public static Brep GenerateTowerSurface(double baseRadius, double waistRadius, double topRadius, double height)
        {
            // 11 rings give a smooth hyperboloid — enough for cubic-eased curvature without control-point noise
            int rings = 11;
            var crvs = new List<Curve>();
            for (int i = 0; i <= rings; i++)
            {
                double t = (double)i / rings;
                double r = SmoothRadius(baseRadius, waistRadius, topRadius, t);
                double z = t * height;
                var circle = new Circle(new Plane(new Point3d(0, 0, z), Vector3d.ZAxis), r);
                crvs.Add(circle.ToNurbsCurve());
            }

            var breps = Brep.CreateFromLoft(crvs, Point3d.Unset, Point3d.Unset, LoftType.Normal, false);
            return breps != null && breps.Length > 0 ? breps[0] : null;
        }

        // Smoothstep between a→b (first half) and b→c (second half)
        private static double SmoothRadius(double a, double b, double c, double t)
        {
            if (t <= 0.5)
            {
                double s = t * 2.0;
                return a + (b - a) * (s * s * (3.0 - 2.0 * s));
            }
            else
            {
                double s = (t - 0.5) * 2.0;
                return b + (c - b) * (s * s * (3.0 - 2.0 * s));
            }
        }

        // Pre-compute the UV grid so generators can share the same point array.
        public static Point3d[,] SampleGridPoints(BrepFace face, int uDivs, int vDivs)
        {
            face.SetDomain(0, new Interval(0, 1));
            face.SetDomain(1, new Interval(0, 1));

            var pts = new Point3d[uDivs + 1, vDivs + 1];
            for (int i = 0; i <= uDivs; i++)
            {
                double u = (double)i / uDivs;
                for (int j = 0; j <= vDivs; j++)
                {
                    double v = (double)j / vDivs;
                    pts[i, j] = face.PointAt(u, v);
                }
            }
            return pts;
        }

        public static List<Curve> GenerateDiagridLines(Point3d[,] pts, int uDivs, int vDivs)
        {
            var lines = new List<Curve>();
            for (int i = 0; i < uDivs; i++)
            {
                for (int j = 0; j < vDivs; j++)
                {
                    lines.Add(new LineCurve(pts[i, j], pts[i + 1, j + 1]));
                    lines.Add(new LineCurve(pts[i + 1, j], pts[i, j + 1]));
                }
            }
            return lines;
        }

        // Quad panel boundaries — used for reference; glass panels are built directly from pts.
        public static List<Curve> GeneratePanels(Point3d[,] pts, int uDivs, int vDivs)
        {
            var panels = new List<Curve>();
            for (int i = 0; i < uDivs; i++)
            {
                for (int j = 0; j < vDivs; j++)
                {
                    var p1 = pts[i, j]; var p2 = pts[i + 1, j];
                    var p3 = pts[i + 1, j + 1]; var p4 = pts[i, j + 1];
                    var quad = new Polyline(new[] { p1, p2, p3, p4, p1 });
                    panels.Add(quad.ToNurbsCurve());
                }
            }
            return panels;
        }
    }
}
