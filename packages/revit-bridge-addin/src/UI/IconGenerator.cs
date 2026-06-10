using System;
using System.IO;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace RevitBridge.UI
{
    /// <summary>
    /// Generates high-end, vector-drawn icon images for Revit ribbon buttons
    /// </summary>
    public static class IconGenerator
    {
        private static bool IsDarkTheme()
        {
            try
            {
                // UIThemeManager is in Autodesk.Revit.UI (Revit 2024+)
                return Autodesk.Revit.UI.UIThemeManager.CurrentTheme == Autodesk.Revit.UI.UITheme.Dark;
            }
            catch
            {
                // Fallback for older Revit versions
                return false;
            }
        }

        /// <summary>
        /// Creates a Connect icon (network node bridge with emerald accent)
        /// </summary>
        public static BitmapSource CreateConnectIcon(int size = 32)
        {
            var visual = new DrawingVisual();
            using (var context = visual.RenderOpen())
            {
                bool isDark = IsDarkTheme();
                var primaryBrush = isDark ? Brushes.White : new SolidColorBrush(Color.FromRgb(30, 41, 59));
                var accentBrush = new SolidColorBrush(Color.FromRgb(46, 125, 50)); // Emerald Green
                var softFillBrush = new SolidColorBrush(Color.FromArgb(40, 46, 125, 50)); // Semi-transparent green
                var pen = new Pen(primaryBrush, size * 0.06) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round, LineJoin = PenLineJoin.Round };
                var accentPen = new Pen(accentBrush, size * 0.06) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round, LineJoin = PenLineJoin.Round };

                // Left node
                context.DrawEllipse(softFillBrush, pen, new Point(size * 0.25, size * 0.65), size * 0.12, size * 0.12);
                // Right node
                context.DrawEllipse(softFillBrush, pen, new Point(size * 0.75, size * 0.65), size * 0.12, size * 0.12);

                // Connecting bridge lines
                context.DrawLine(pen, new Point(size * 0.37, size * 0.65), new Point(size * 0.63, size * 0.65));

                // Server/AI node (Top center)
                var geometry = new PathGeometry();
                var figure = new PathFigure { StartPoint = new Point(size * 0.5, size * 0.18), IsClosed = true };
                figure.Segments.Add(new LineSegment(new Point(size * 0.65, size * 0.45), true));
                figure.Segments.Add(new LineSegment(new Point(size * 0.35, size * 0.45), true));
                geometry.Figures.Add(figure);
                context.DrawGeometry(softFillBrush, accentPen, geometry);

                // Connector lines from bottom nodes to top server node
                context.DrawLine(pen, new Point(size * 0.25, size * 0.53), new Point(size * 0.42, size * 0.4));
                context.DrawLine(pen, new Point(size * 0.75, size * 0.53), new Point(size * 0.58, size * 0.4));
            }

            return RenderVisual(visual, size, size);
        }

        /// <summary>
        /// Creates a Disconnect icon (network node bridge with broken links and crimson cancel slash)
        /// </summary>
        public static BitmapSource CreateDisconnectIcon(int size = 32)
        {
            var visual = new DrawingVisual();
            using (var context = visual.RenderOpen())
            {
                bool isDark = IsDarkTheme();
                var primaryBrush = isDark ? Brushes.White : new SolidColorBrush(Color.FromRgb(30, 41, 59));
                var accentBrush = new SolidColorBrush(Color.FromRgb(211, 47, 47)); // Crimson Red
                var pen = new Pen(primaryBrush, size * 0.06) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round, LineJoin = PenLineJoin.Round };

                // Left node
                context.DrawEllipse(null, pen, new Point(size * 0.25, size * 0.65), size * 0.12, size * 0.12);
                // Right node
                context.DrawEllipse(null, pen, new Point(size * 0.75, size * 0.65), size * 0.12, size * 0.12);

                // Top server node
                var geometry = new PathGeometry();
                var figure = new PathFigure { StartPoint = new Point(size * 0.5, size * 0.18), IsClosed = true };
                figure.Segments.Add(new LineSegment(new Point(size * 0.65, size * 0.45), true));
                figure.Segments.Add(new LineSegment(new Point(size * 0.35, size * 0.45), true));
                geometry.Figures.Add(figure);
                context.DrawGeometry(null, pen, geometry);

                // Broken connections
                context.DrawLine(pen, new Point(size * 0.25, size * 0.53), new Point(size * 0.35, size * 0.46));
                context.DrawLine(pen, new Point(size * 0.75, size * 0.53), new Point(size * 0.65, size * 0.46));

                // Crimson cancel slash
                var slashPen = new Pen(accentBrush, size * 0.08) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round };
                context.DrawLine(slashPen, new Point(size * 0.4, size * 0.35), new Point(size * 0.6, size * 0.55));
                context.DrawLine(slashPen, new Point(size * 0.6, size * 0.35), new Point(size * 0.4, size * 0.55));
            }

            return RenderVisual(visual, size, size);
        }

        /// <summary>
        /// Creates a Status icon (sleek dashboard grid with active blue communication indicator)
        /// </summary>
        public static BitmapSource CreateStatusIcon(int size = 32)
        {
            var visual = new DrawingVisual();
            using (var context = visual.RenderOpen())
            {
                bool isDark = IsDarkTheme();
                var primaryBrush = isDark ? Brushes.White : new SolidColorBrush(Color.FromRgb(30, 41, 59));
                var accentBrush = new SolidColorBrush(Color.FromRgb(2, 136, 209)); // Autodesk Blue
                var softFillBrush = new SolidColorBrush(Color.FromArgb(40, 2, 136, 209)); // Semi-transparent blue
                var pen = new Pen(primaryBrush, size * 0.06) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round, LineJoin = PenLineJoin.Round };
                var accentPen = new Pen(accentBrush, size * 0.06) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round };

                // Outer dashboard window
                context.DrawRoundedRectangle(null, pen, new Rect(size * 0.15, size * 0.15, size * 0.7, size * 0.7), size * 0.08, size * 0.08);

                // Grid lines inside status card
                context.DrawLine(pen, new Point(size * 0.25, size * 0.35), new Point(size * 0.5, size * 0.35));
                context.DrawLine(pen, new Point(size * 0.25, size * 0.55), new Point(size * 0.45, size * 0.55));

                // Glowing blue pulse/indicator dot
                context.DrawEllipse(softFillBrush, accentPen, new Point(size * 0.68, size * 0.65), size * 0.12, size * 0.12);
                context.DrawEllipse(accentBrush, null, new Point(size * 0.68, size * 0.65), size * 0.05, size * 0.05);
            }

            return RenderVisual(visual, size, size);
        }

        /// <summary>
        /// Creates a Settings icon (geometrical gear wheel)
        /// </summary>
        public static BitmapSource CreateSettingsIcon(int size = 32)
        {
            var visual = new DrawingVisual();
            using (var context = visual.RenderOpen())
            {
                bool isDark = IsDarkTheme();
                var primaryBrush = isDark ? Brushes.White : new SolidColorBrush(Color.FromRgb(30, 41, 59));
                var pen = new Pen(primaryBrush, size * 0.06) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round, LineJoin = PenLineJoin.Round };

                double cX = size / 2.0;
                double cY = size / 2.0;
                double rOuter = size * 0.25;
                double rInner = size * 0.12;

                // Center shaft circle
                context.DrawEllipse(null, pen, new Point(cX, cY), rInner, rInner);

                // Gear teeth
                int teeth = 6;
                double toothHeight = size * 0.08;
                for (int i = 0; i < teeth; i++)
                {
                    double angle = (Math.PI * 2 * i) / teeth;
                    double cos = Math.Cos(angle);
                    double sin = Math.Sin(angle);

                    Point pStart = new Point(cX + rOuter * cos, cY + rOuter * sin);
                    Point pEnd = new Point(cX + (rOuter + toothHeight) * cos, cY + (rOuter + toothHeight) * sin);

                    var toothPen = new Pen(primaryBrush, size * 0.08) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round };
                    context.DrawLine(toothPen, pStart, pEnd);
                }

                // Outer gear ring
                context.DrawEllipse(null, pen, new Point(cX, cY), rOuter, rOuter);
            }

            return RenderVisual(visual, size, size);
        }

        /// <summary>
        /// Creates a Help icon (question mark inside a circular balloon)
        /// </summary>
        public static BitmapSource CreateHelpIcon(int size = 32)
        {
            var visual = new DrawingVisual();
            using (var context = visual.RenderOpen())
            {
                bool isDark = IsDarkTheme();
                var primaryBrush = isDark ? Brushes.White : new SolidColorBrush(Color.FromRgb(30, 41, 59));
                var accentBrush = new SolidColorBrush(Color.FromRgb(0, 150, 136)); // Teal
                var softFillBrush = new SolidColorBrush(Color.FromArgb(40, 0, 150, 136)); // Semi-transparent teal
                var pen = new Pen(primaryBrush, size * 0.06) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round };

                // Balloon outline
                context.DrawEllipse(softFillBrush, pen, new Point(size / 2.0, size / 2.0), size * 0.35, size * 0.35);

                // Question mark text drawing
                var formattedText = new FormattedText(
                    "?",
                    System.Globalization.CultureInfo.InvariantCulture,
                    FlowDirection.LeftToRight,
                    new Typeface(new FontFamily("Segoe UI"), FontStyles.Normal, FontWeights.Bold, FontStretches.Normal),
                    size * 0.45,
                    primaryBrush,
                    96);

                context.DrawText(formattedText, new Point(size * 0.38, size * 0.2));
            }

            return RenderVisual(visual, size, size);
        }

        /// <summary>
        /// Creates the generic AEC Model Bridge icon.
        /// </summary>
        public static BitmapSource CreateBrandIcon(int size = 32)
        {
            var visual = new DrawingVisual();
            using (var context = visual.RenderOpen())
            {
                double cX = size / 2.0;

                // Gradient faces for a generic building-model cube.
                var topBrush = new LinearGradientBrush(Color.FromRgb(0, 188, 212), Color.FromRgb(0, 150, 136), 45); // Cyan to Teal
                var leftBrush = new LinearGradientBrush(Color.FromRgb(33, 150, 243), Color.FromRgb(21, 101, 192), 90); // Blue to Dark Blue
                var rightBrush = new LinearGradientBrush(Color.FromRgb(0, 150, 136), Color.FromRgb(0, 105, 92), 90); // Dark Teal

                var pen = new Pen(Brushes.White, size * 0.04) { LineJoin = PenLineJoin.Round };

                // Isometric vertices
                Point topPt = new Point(cX, size * 0.15);
                Point leftPt = new Point(size * 0.15, size * 0.38);
                Point rightPt = new Point(size * 0.85, size * 0.38);
                Point centerPt = new Point(cX, size * 0.58);
                Point botLeftPt = new Point(size * 0.15, size * 0.78);
                Point botRightPt = new Point(size * 0.85, size * 0.78);
                Point bottomPt = new Point(cX, size * 0.95);

                // Top Face
                var topGeo = new PathGeometry();
                var topFig = new PathFigure { StartPoint = topPt, IsClosed = true };
                topFig.Segments.Add(new LineSegment(leftPt, true));
                topFig.Segments.Add(new LineSegment(centerPt, true));
                topFig.Segments.Add(new LineSegment(rightPt, true));
                topGeo.Figures.Add(topFig);
                context.DrawGeometry(topBrush, pen, topGeo);

                // Left Face
                var leftGeo = new PathGeometry();
                var leftFig = new PathFigure { StartPoint = leftPt, IsClosed = true };
                leftFig.Segments.Add(new LineSegment(botLeftPt, true));
                leftFig.Segments.Add(new LineSegment(bottomPt, true));
                leftFig.Segments.Add(new LineSegment(centerPt, true));
                leftGeo.Figures.Add(leftFig);
                context.DrawGeometry(leftBrush, pen, leftGeo);

                // Right Face
                var rightGeo = new PathGeometry();
                var rightFig = new PathFigure { StartPoint = rightPt, IsClosed = true };
                rightFig.Segments.Add(new LineSegment(centerPt, true));
                rightFig.Segments.Add(new LineSegment(bottomPt, true));
                rightFig.Segments.Add(new LineSegment(botRightPt, true));
                rightGeo.Figures.Add(rightFig);
                context.DrawGeometry(rightBrush, pen, rightGeo);
            }

            return RenderVisual(visual, size, size);
        }

        private static BitmapSource RenderVisual(DrawingVisual visual, int width, int height)
        {
            var bitmap = new RenderTargetBitmap(width, height, 96, 96, PixelFormats.Pbgra32);
            bitmap.Render(visual);
            bitmap.Freeze();
            return bitmap;
        }

        /// <summary>
        /// Saves an icon to a file
        /// </summary>
        public static void SaveIcon(BitmapSource icon, string filePath)
        {
            var encoder = new PngBitmapEncoder();
            encoder.Frames.Add(BitmapFrame.Create(icon));

            Directory.CreateDirectory(Path.GetDirectoryName(filePath) ?? "");

            using (var stream = new FileStream(filePath, FileMode.Create))
            {
                encoder.Save(stream);
            }
        }

        /// <summary>
        /// Generates all ribbon button icons and saves them to the specified directory
        /// </summary>
        public static void GenerateAllIcons(string iconDir)
        {
            SaveIcon(CreateConnectIcon(32), Path.Combine(iconDir, "connect.png"));
            SaveIcon(CreateDisconnectIcon(32), Path.Combine(iconDir, "disconnect.png"));
            SaveIcon(CreateStatusIcon(32), Path.Combine(iconDir, "status.png"));
            SaveIcon(CreateSettingsIcon(32), Path.Combine(iconDir, "settings.png"));
            SaveIcon(CreateBrandIcon(32), Path.Combine(iconDir, "brand.png"));
            SaveIcon(CreateHelpIcon(32), Path.Combine(iconDir, "help.png"));
        }
    }
}
