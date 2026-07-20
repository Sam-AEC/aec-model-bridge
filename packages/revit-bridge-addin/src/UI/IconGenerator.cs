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
        private static double StrokeWidth(int size, double scale)
        {
            if (size <= 16)
            {
                return scale >= 0.075 ? 2.0 : 1.5;
            }

            return Math.Max(
                1.5,
                Math.Round(size * scale * 2, MidpointRounding.AwayFromZero) / 2);
        }

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
        /// Creates a Connect icon (network node bridge fully accented in emerald green)
        /// </summary>
        public static BitmapSource CreateConnectIcon(int size = 32)
        {
            var visual = new DrawingVisual();
            using (var context = visual.RenderOpen())
            {
                var accentBrush = new SolidColorBrush(Color.FromRgb(46, 125, 50)); // Emerald Green
                var softFillBrush = new SolidColorBrush(Color.FromArgb(64, 46, 125, 50)); // Semi-transparent green
                var accentPen = new Pen(accentBrush, StrokeWidth(size, 0.06)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round, LineJoin = PenLineJoin.Round };

                // Left node
                context.DrawEllipse(softFillBrush, accentPen, new Point(size * 0.19, size * 0.72), size * 0.14, size * 0.14);
                // Right node
                context.DrawEllipse(softFillBrush, accentPen, new Point(size * 0.81, size * 0.72), size * 0.14, size * 0.14);

                // Connecting bridge lines
                context.DrawLine(accentPen, new Point(size * 0.33, size * 0.72), new Point(size * 0.67, size * 0.72));

                // Server/AI node (Top center)
                var geometry = new PathGeometry();
                var figure = new PathFigure { StartPoint = new Point(size * 0.5, size * 0.07), IsClosed = true };
                figure.Segments.Add(new LineSegment(new Point(size * 0.68, size * 0.42), true));
                figure.Segments.Add(new LineSegment(new Point(size * 0.32, size * 0.42), true));
                geometry.Figures.Add(figure);
                context.DrawGeometry(softFillBrush, accentPen, geometry);

                // Connector lines from bottom nodes to top server node
                context.DrawLine(accentPen, new Point(size * 0.27, size * 0.61), new Point(size * 0.38, size * 0.40));
                context.DrawLine(accentPen, new Point(size * 0.73, size * 0.61), new Point(size * 0.62, size * 0.40));
            }

            return RenderVisual(visual, size, size);
        }

        /// <summary>
        /// Creates a Disconnect icon (network node bridge fully accented in crimson red with cancel slash)
        /// </summary>
        public static BitmapSource CreateDisconnectIcon(int size = 32)
        {
            var visual = new DrawingVisual();
            using (var context = visual.RenderOpen())
            {
                var accentBrush = new SolidColorBrush(Color.FromRgb(211, 47, 47)); // Crimson Red
                var softFillBrush = new SolidColorBrush(Color.FromArgb(32, 211, 47, 47)); // Very transparent red for nodes
                var accentPen = new Pen(accentBrush, StrokeWidth(size, 0.06)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round, LineJoin = PenLineJoin.Round };

                // Left node
                context.DrawEllipse(softFillBrush, accentPen, new Point(size * 0.19, size * 0.72), size * 0.14, size * 0.14);
                // Right node
                context.DrawEllipse(softFillBrush, accentPen, new Point(size * 0.81, size * 0.72), size * 0.14, size * 0.14);

                // Top server node
                var geometry = new PathGeometry();
                var figure = new PathFigure { StartPoint = new Point(size * 0.5, size * 0.07), IsClosed = true };
                figure.Segments.Add(new LineSegment(new Point(size * 0.68, size * 0.42), true));
                figure.Segments.Add(new LineSegment(new Point(size * 0.32, size * 0.42), true));
                geometry.Figures.Add(figure);
                context.DrawGeometry(softFillBrush, accentPen, geometry);

                // Broken connections
                context.DrawLine(accentPen, new Point(size * 0.27, size * 0.61), new Point(size * 0.36, size * 0.44));
                context.DrawLine(accentPen, new Point(size * 0.73, size * 0.61), new Point(size * 0.64, size * 0.44));

                // Crimson cancel slash
                var slashPen = new Pen(accentBrush, StrokeWidth(size, 0.08)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round };
                context.DrawLine(slashPen, new Point(size * 0.36, size * 0.32), new Point(size * 0.64, size * 0.60));
                context.DrawLine(slashPen, new Point(size * 0.64, size * 0.32), new Point(size * 0.36, size * 0.60));
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
                var softFillBrush = new SolidColorBrush(Color.FromArgb(64, 2, 136, 209)); // Semi-transparent blue
                var pen = new Pen(primaryBrush, StrokeWidth(size, 0.06)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round, LineJoin = PenLineJoin.Round };
                var accentPen = new Pen(accentBrush, StrokeWidth(size, 0.06)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round };

                // Outer dashboard window
                context.DrawRoundedRectangle(null, pen, new Rect(size * 0.07, size * 0.07, size * 0.86, size * 0.86), size * 0.09, size * 0.09);

                // Grid lines inside status card
                context.DrawLine(pen, new Point(size * 0.19, size * 0.32), new Point(size * 0.58, size * 0.32));
                context.DrawLine(pen, new Point(size * 0.19, size * 0.53), new Point(size * 0.50, size * 0.53));

                // Glowing blue pulse/indicator dot
                context.DrawEllipse(softFillBrush, accentPen, new Point(size * 0.73, size * 0.72), size * 0.14, size * 0.14);
                context.DrawEllipse(accentBrush, null, new Point(size * 0.73, size * 0.72), size * 0.055, size * 0.055);
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
                var pen = new Pen(primaryBrush, StrokeWidth(size, 0.06)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round, LineJoin = PenLineJoin.Round };

                double cX = size / 2.0;
                double cY = size / 2.0;
                double rOuter = size * 0.30;
                double rInner = size * 0.12;

                // Center shaft circle
                context.DrawEllipse(null, pen, new Point(cX, cY), rInner, rInner);

                // Gear teeth
                int teeth = 6;
                double toothHeight = size * 0.11;
                for (int i = 0; i < teeth; i++)
                {
                    double angle = (Math.PI * 2 * i) / teeth;
                    double cos = Math.Cos(angle);
                    double sin = Math.Sin(angle);

                    Point pStart = new Point(cX + rOuter * cos, cY + rOuter * sin);
                    Point pEnd = new Point(cX + (rOuter + toothHeight) * cos, cY + (rOuter + toothHeight) * sin);

                    var toothPen = new Pen(primaryBrush, StrokeWidth(size, 0.08)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round };
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
                var softFillBrush = new SolidColorBrush(Color.FromArgb(64, 0, 150, 136)); // Semi-transparent teal
                var pen = new Pen(primaryBrush, StrokeWidth(size, 0.06)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round };

                // Balloon outline
                context.DrawEllipse(softFillBrush, pen, new Point(size / 2.0, size / 2.0), size * 0.42, size * 0.42);

                // Question mark text drawing
                var formattedText = new FormattedText(
                    "?",
                    System.Globalization.CultureInfo.InvariantCulture,
                    FlowDirection.LeftToRight,
                    new Typeface(new FontFamily("Segoe UI"), FontStyles.Normal, FontWeights.Bold, FontStretches.Normal),
                    size * 0.54,
                    primaryBrush,
                    96);

                context.DrawText(formattedText, new Point(size * 0.35, size * 0.11));
            }

            return RenderVisual(visual, size, size);
        }

        /// <summary>
        /// Creates a dockable-panel icon (frame with a filled docked side panel) for Open Panel.
        /// </summary>
        public static BitmapSource CreatePanelIcon(int size = 32)
        {
            var visual = new DrawingVisual();
            using (var context = visual.RenderOpen())
            {
                bool isDark = IsDarkTheme();
                var primaryBrush = isDark ? Brushes.White : new SolidColorBrush(Color.FromRgb(30, 41, 59));
                var accentBrush = new SolidColorBrush(Color.FromRgb(63, 81, 181)); // Indigo
                var softFillBrush = new SolidColorBrush(Color.FromArgb(90, 63, 81, 181)); // Semi-transparent indigo
                var pen = new Pen(primaryBrush, StrokeWidth(size, 0.06)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round, LineJoin = PenLineJoin.Round };
                var accentPen = new Pen(accentBrush, StrokeWidth(size, 0.05)) { LineJoin = PenLineJoin.Round };

                // Outer window frame
                context.DrawRoundedRectangle(null, pen, new Rect(size * 0.07, size * 0.07, size * 0.86, size * 0.86), size * 0.09, size * 0.09);

                // Docked side panel (filled, right third)
                context.DrawRectangle(softFillBrush, accentPen, new Rect(size * 0.63, size * 0.09, size * 0.28, size * 0.82));

                // Content rows in the main area
                context.DrawLine(pen, new Point(size * 0.17, size * 0.30), new Point(size * 0.53, size * 0.30));
                context.DrawLine(pen, new Point(size * 0.17, size * 0.50), new Point(size * 0.46, size * 0.50));
            }

            return RenderVisual(visual, size, size);
        }

        /// <summary>
        /// Creates a health-check icon (clipboard with a checkmark) for QA/QC model health checks.
        /// </summary>
        public static BitmapSource CreateHealthIcon(int size = 32)
        {
            var visual = new DrawingVisual();
            using (var context = visual.RenderOpen())
            {
                bool isDark = IsDarkTheme();
                var primaryBrush = isDark ? Brushes.White : new SolidColorBrush(Color.FromRgb(30, 41, 59));
                var accentBrush = new SolidColorBrush(Color.FromRgb(245, 124, 0)); // Amber
                var pen = new Pen(primaryBrush, StrokeWidth(size, 0.06)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round, LineJoin = PenLineJoin.Round };
                var accentPen = new Pen(accentBrush, StrokeWidth(size, 0.09)) { StartLineCap = PenLineCap.Round, LineJoin = PenLineJoin.Round };

                // Clipboard body
                context.DrawRoundedRectangle(null, pen, new Rect(size * 0.20, size * 0.12, size * 0.60, size * 0.78), size * 0.06, size * 0.06);

                // Clip tab
                context.DrawRoundedRectangle(isDark ? Brushes.Black : Brushes.White, pen, new Rect(size * 0.38, size * 0.05, size * 0.24, size * 0.11), size * 0.03, size * 0.03);

                // Checkmark
                var check = new PathGeometry();
                var checkFig = new PathFigure { StartPoint = new Point(size * 0.32, size * 0.53), IsClosed = false };
                checkFig.Segments.Add(new LineSegment(new Point(size * 0.45, size * 0.66), true));
                checkFig.Segments.Add(new LineSegment(new Point(size * 0.70, size * 0.36), true));
                check.Figures.Add(checkFig);
                context.DrawGeometry(null, accentPen, check);
            }

            return RenderVisual(visual, size, size);
        }

        /// <summary>
        /// Creates a pending-actions icon (list rows with a clock badge) for the approval queue.
        /// </summary>
        public static BitmapSource CreatePendingIcon(int size = 32)
        {
            var visual = new DrawingVisual();
            using (var context = visual.RenderOpen())
            {
                bool isDark = IsDarkTheme();
                var primaryBrush = isDark ? Brushes.White : new SolidColorBrush(Color.FromRgb(30, 41, 59));
                var accentBrush = new SolidColorBrush(Color.FromRgb(123, 31, 162)); // Violet
                var softFillBrush = new SolidColorBrush(Color.FromArgb(64, 123, 31, 162));
                var pen = new Pen(primaryBrush, StrokeWidth(size, 0.07)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round };
                var accentPen = new Pen(accentBrush, StrokeWidth(size, 0.055)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round, LineJoin = PenLineJoin.Round };

                // Queued list rows (descending widths, top-left)
                context.DrawLine(pen, new Point(size * 0.10, size * 0.22), new Point(size * 0.62, size * 0.22));
                context.DrawLine(pen, new Point(size * 0.10, size * 0.42), new Point(size * 0.54, size * 0.42));
                context.DrawLine(pen, new Point(size * 0.10, size * 0.62), new Point(size * 0.42, size * 0.62));

                // Clock badge (bottom-right) — the "pending/awaiting" marker
                var badgeCenter = new Point(size * 0.74, size * 0.76);
                double badgeR = size * 0.23;
                context.DrawEllipse(softFillBrush, accentPen, badgeCenter, badgeR, badgeR);
                context.DrawLine(accentPen, badgeCenter, new Point(badgeCenter.X, badgeCenter.Y - badgeR * 0.55));
                context.DrawLine(accentPen, badgeCenter, new Point(badgeCenter.X + badgeR * 0.45, badgeCenter.Y + badgeR * 0.1));
            }

            return RenderVisual(visual, size, size);
        }

        /// <summary>
        /// Creates a reports icon (ascending bar chart) for report export tools.
        /// </summary>
        public static BitmapSource CreateReportsIcon(int size = 32)
        {
            var visual = new DrawingVisual();
            using (var context = visual.RenderOpen())
            {
                bool isDark = IsDarkTheme();
                var primaryBrush = isDark ? Brushes.White : new SolidColorBrush(Color.FromRgb(30, 41, 59));
                var accentBrush = new SolidColorBrush(Color.FromRgb(25, 118, 210)); // Blue
                var softFillBrush = new SolidColorBrush(Color.FromArgb(90, 25, 118, 210));
                var pen = new Pen(primaryBrush, StrokeWidth(size, 0.06)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round };
                var accentPen = new Pen(accentBrush, StrokeWidth(size, 0.05)) { LineJoin = PenLineJoin.Round };

                double baseline = size * 0.86;
                double barWidth = size * 0.17;

                context.DrawRectangle(softFillBrush, accentPen, new Rect(size * 0.15, size * 0.58, barWidth, baseline - size * 0.58));
                context.DrawRectangle(softFillBrush, accentPen, new Rect(size * 0.415, size * 0.40, barWidth, baseline - size * 0.40));
                context.DrawRectangle(softFillBrush, accentPen, new Rect(size * 0.68, size * 0.22, barWidth, baseline - size * 0.22));

                // Baseline
                context.DrawLine(pen, new Point(size * 0.10, baseline), new Point(size * 0.90, baseline));
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

                var pen = new Pen(Brushes.White, StrokeWidth(size, 0.04)) { LineJoin = PenLineJoin.Round };

                // Isometric vertices
                Point topPt = new Point(cX, size * 0.07);
                Point leftPt = new Point(size * 0.08, size * 0.34);
                Point rightPt = new Point(size * 0.92, size * 0.34);
                Point centerPt = new Point(cX, size * 0.56);
                Point botLeftPt = new Point(size * 0.08, size * 0.76);
                Point botRightPt = new Point(size * 0.92, size * 0.76);
                Point bottomPt = new Point(cX, size * 0.94);

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
        /// Generates all ribbon button icons (both 16x16 and 32x32) and saves them to the specified directory
        /// </summary>
        public static void GenerateAllIcons(string iconDir)
        {
            // 32x32 icons for Revit large buttons and legacy fallbacks.
            SaveIcon(CreateConnectIcon(32), Path.Combine(iconDir, "connect_32.png"));
            SaveIcon(CreateConnectIcon(32), Path.Combine(iconDir, "connect.png"));
            SaveIcon(CreateDisconnectIcon(32), Path.Combine(iconDir, "disconnect_32.png"));
            SaveIcon(CreateDisconnectIcon(32), Path.Combine(iconDir, "disconnect.png"));
            SaveIcon(CreateStatusIcon(32), Path.Combine(iconDir, "status_32.png"));
            SaveIcon(CreateStatusIcon(32), Path.Combine(iconDir, "status.png"));
            SaveIcon(CreateSettingsIcon(32), Path.Combine(iconDir, "settings_32.png"));
            SaveIcon(CreateSettingsIcon(32), Path.Combine(iconDir, "settings.png"));
            SaveIcon(CreateBrandIcon(32), Path.Combine(iconDir, "brand_32.png"));
            SaveIcon(CreateBrandIcon(32), Path.Combine(iconDir, "brand.png"));
            SaveIcon(CreateHelpIcon(32), Path.Combine(iconDir, "help_32.png"));
            SaveIcon(CreateHelpIcon(32), Path.Combine(iconDir, "help.png"));
            SaveIcon(CreatePanelIcon(32), Path.Combine(iconDir, "panel_32.png"));
            SaveIcon(CreatePanelIcon(32), Path.Combine(iconDir, "panel.png"));
            SaveIcon(CreateHealthIcon(32), Path.Combine(iconDir, "healthcheck_32.png"));
            SaveIcon(CreateHealthIcon(32), Path.Combine(iconDir, "healthcheck.png"));
            SaveIcon(CreatePendingIcon(32), Path.Combine(iconDir, "pending_32.png"));
            SaveIcon(CreatePendingIcon(32), Path.Combine(iconDir, "pending.png"));
            SaveIcon(CreateReportsIcon(32), Path.Combine(iconDir, "reports_32.png"));
            SaveIcon(CreateReportsIcon(32), Path.Combine(iconDir, "reports.png"));

            // 16x16 icons for Revit small buttons and stacked items.
            SaveIcon(CreateConnectIcon(16), Path.Combine(iconDir, "connect_16.png"));
            SaveIcon(CreateDisconnectIcon(16), Path.Combine(iconDir, "disconnect_16.png"));
            SaveIcon(CreateStatusIcon(16), Path.Combine(iconDir, "status_16.png"));
            SaveIcon(CreateSettingsIcon(16), Path.Combine(iconDir, "settings_16.png"));
            SaveIcon(CreateBrandIcon(16), Path.Combine(iconDir, "brand_16.png"));
            SaveIcon(CreateHelpIcon(16), Path.Combine(iconDir, "help_16.png"));
            SaveIcon(CreatePanelIcon(16), Path.Combine(iconDir, "panel_16.png"));
            SaveIcon(CreateHealthIcon(16), Path.Combine(iconDir, "healthcheck_16.png"));
            SaveIcon(CreatePendingIcon(16), Path.Combine(iconDir, "pending_16.png"));
            SaveIcon(CreateReportsIcon(16), Path.Combine(iconDir, "reports_16.png"));
        }
    }
}
