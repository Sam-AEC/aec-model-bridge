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
        // keep in sync with docs/design/tokens.md
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
        /// Creates a Connect icon (the Span mark, monochrome in the success accent)
        /// </summary>
        public static BitmapSource CreateConnectIcon(int size = 32)
        {
            var visual = new DrawingVisual();
            using (var context = visual.RenderOpen())
            {
                bool isDark = IsDarkTheme();
                var successRgb = isDark ? Color.FromRgb(63, 203, 139) : Color.FromRgb(18, 122, 75); // amb-success
                var washBrush = new SolidColorBrush(Color.FromArgb(51, successRgb.R, successRgb.G, successRgb.B));
                var strokeBrush = new SolidColorBrush(successRgb);
                var pen = new Pen(strokeBrush, StrokeWidth(size, 0.06)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round, LineJoin = PenLineJoin.Round };

                // Node, left (wash + stroke)
                context.DrawEllipse(washBrush, pen, new Point(size * 0.190, size * 0.725), size * 0.140, size * 0.140);
                // Node, right (wash + stroke)
                context.DrawEllipse(washBrush, pen, new Point(size * 0.810, size * 0.725), size * 0.140, size * 0.140);

                // Deck
                context.DrawLine(pen, new Point(size * 0.330, size * 0.725), new Point(size * 0.670, size * 0.725));

                // Apex (wash + stroke)
                var apexGeometry = new PathGeometry();
                var apexFigure = new PathFigure { StartPoint = new Point(size * 0.500, size * 0.085), IsClosed = true };
                apexFigure.Segments.Add(new LineSegment(new Point(size * 0.670, size * 0.430), true));
                apexFigure.Segments.Add(new LineSegment(new Point(size * 0.330, size * 0.430), true));
                apexGeometry.Figures.Add(apexFigure);
                context.DrawGeometry(washBrush, pen, apexGeometry);
            }

            return RenderVisual(visual, size, size);
        }

        /// <summary>
        /// Creates a Disconnect icon (the Span mark, monochrome in the danger accent, with a single cancel slash)
        /// </summary>
        public static BitmapSource CreateDisconnectIcon(int size = 32)
        {
            var visual = new DrawingVisual();
            using (var context = visual.RenderOpen())
            {
                bool isDark = IsDarkTheme();
                var dangerRgb = isDark ? Color.FromRgb(240, 121, 107) : Color.FromRgb(194, 59, 46); // amb-danger
                var washBrush = new SolidColorBrush(Color.FromArgb(51, dangerRgb.R, dangerRgb.G, dangerRgb.B));
                var strokeBrush = new SolidColorBrush(dangerRgb);
                var pen = new Pen(strokeBrush, StrokeWidth(size, 0.06)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round, LineJoin = PenLineJoin.Round };

                // Node, left (wash + stroke)
                context.DrawEllipse(washBrush, pen, new Point(size * 0.190, size * 0.725), size * 0.140, size * 0.140);
                // Node, right (wash + stroke)
                context.DrawEllipse(washBrush, pen, new Point(size * 0.810, size * 0.725), size * 0.140, size * 0.140);

                // Deck
                context.DrawLine(pen, new Point(size * 0.330, size * 0.725), new Point(size * 0.670, size * 0.725));

                // Apex (wash + stroke)
                var apexGeometry = new PathGeometry();
                var apexFigure = new PathFigure { StartPoint = new Point(size * 0.500, size * 0.085), IsClosed = true };
                apexFigure.Segments.Add(new LineSegment(new Point(size * 0.670, size * 0.430), true));
                apexFigure.Segments.Add(new LineSegment(new Point(size * 0.330, size * 0.430), true));
                apexGeometry.Figures.Add(apexFigure);
                context.DrawGeometry(washBrush, pen, apexGeometry);

                // Cancel slash — a single diagonal, not a cross
                var slashPen = new Pen(strokeBrush, StrokeWidth(size, 0.08)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round };
                context.DrawLine(slashPen, new Point(size * 0.300, size * 0.290), new Point(size * 0.700, size * 0.690));
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
                var primaryBrush = isDark ? new SolidColorBrush(Color.FromRgb(233, 238, 245)) : new SolidColorBrush(Color.FromRgb(24, 32, 44)); // amb-ink
                var infoRgb = isDark ? Color.FromRgb(127, 166, 245) : Color.FromRgb(36, 87, 197); // amb-info
                var accentBrush = new SolidColorBrush(infoRgb);
                var softFillBrush = new SolidColorBrush(Color.FromArgb(51, infoRgb.R, infoRgb.G, infoRgb.B));
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
                var inkRgb = isDark ? Color.FromRgb(233, 238, 245) : Color.FromRgb(24, 32, 44); // amb-ink
                var primaryBrush = new SolidColorBrush(inkRgb);
                var softFillBrush = new SolidColorBrush(Color.FromArgb(isDark ? (byte)41 : (byte)31, inkRgb.R, inkRgb.G, inkRgb.B));
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
                var inkRgb = isDark ? Color.FromRgb(233, 238, 245) : Color.FromRgb(24, 32, 44); // amb-ink
                var primaryBrush = new SolidColorBrush(inkRgb);
                var softFillBrush = new SolidColorBrush(Color.FromArgb(isDark ? (byte)41 : (byte)31, inkRgb.R, inkRgb.G, inkRgb.B));
                var pen = new Pen(primaryBrush, StrokeWidth(size, 0.06)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round, LineJoin = PenLineJoin.Round };
                var accentPen = new Pen(primaryBrush, StrokeWidth(size, 0.05)) { LineJoin = PenLineJoin.Round };

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
                var primaryBrush = isDark ? new SolidColorBrush(Color.FromRgb(233, 238, 245)) : new SolidColorBrush(Color.FromRgb(24, 32, 44)); // amb-ink
                var accentBrush = new SolidColorBrush(isDark ? Color.FromRgb(242, 166, 60) : Color.FromRgb(164, 95, 11)); // amb-warning
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
                var primaryBrush = isDark ? new SolidColorBrush(Color.FromRgb(233, 238, 245)) : new SolidColorBrush(Color.FromRgb(24, 32, 44)); // amb-ink
                var accentRgb = isDark ? Color.FromRgb(183, 154, 240) : Color.FromRgb(109, 63, 184); // amb-pending
                var accentBrush = new SolidColorBrush(accentRgb);
                var softFillBrush = new SolidColorBrush(Color.FromArgb(51, accentRgb.R, accentRgb.G, accentRgb.B));
                var pen = new Pen(primaryBrush, StrokeWidth(size, 0.07)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round };
                var accentPen = new Pen(accentBrush, StrokeWidth(size, 0.055)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round, LineJoin = PenLineJoin.Round };

                // Queued list rows (descending widths, top-left)
                context.DrawLine(pen, new Point(size * 0.10, size * 0.22), new Point(size * 0.62, size * 0.22));
                context.DrawLine(pen, new Point(size * 0.10, size * 0.42), new Point(size * 0.54, size * 0.42));
                context.DrawLine(pen, new Point(size * 0.10, size * 0.62), new Point(size * 0.42, size * 0.62));

                // Clock badge (bottom-right) — the "pending/awaiting" marker
                var badgeCenter = new Point(size * 0.730, size * 0.740);
                double badgeR = size * 0.210;
                context.DrawEllipse(softFillBrush, accentPen, badgeCenter, badgeR, badgeR);
                context.DrawLine(accentPen, badgeCenter, new Point(size * 0.730, size * 0.6245));
                context.DrawLine(accentPen, badgeCenter, new Point(size * 0.825, size * 0.761));
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
                var inkRgb = isDark ? Color.FromRgb(233, 238, 245) : Color.FromRgb(24, 32, 44); // amb-ink
                var primaryBrush = new SolidColorBrush(inkRgb);
                var softFillBrush = new SolidColorBrush(Color.FromArgb(isDark ? (byte)41 : (byte)31, inkRgb.R, inkRgb.G, inkRgb.B));
                var pen = new Pen(primaryBrush, StrokeWidth(size, 0.06)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round };
                var accentPen = new Pen(primaryBrush, StrokeWidth(size, 0.05)) { LineJoin = PenLineJoin.Round };

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
        /// Creates the AEC Model Bridge brand icon (the Span mark, two-tone: ink structure, brand apex).
        /// </summary>
        public static BitmapSource CreateBrandIcon(int size = 32)
        {
            var visual = new DrawingVisual();
            using (var context = visual.RenderOpen())
            {
                bool isDark = IsDarkTheme();
                var inkRgb = isDark ? Color.FromRgb(233, 238, 245) : Color.FromRgb(24, 32, 44); // amb-ink
                var brandRgb = isDark ? Color.FromRgb(63, 195, 214) : Color.FromRgb(0, 145, 167); // amb-brand

                var inkWashBrush = new SolidColorBrush(Color.FromArgb(isDark ? (byte)41 : (byte)31, inkRgb.R, inkRgb.G, inkRgb.B));
                var inkPen = new Pen(new SolidColorBrush(inkRgb), StrokeWidth(size, 0.06)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round, LineJoin = PenLineJoin.Round };

                var brandWashBrush = new SolidColorBrush(Color.FromArgb(51, brandRgb.R, brandRgb.G, brandRgb.B));
                var brandPen = new Pen(new SolidColorBrush(brandRgb), StrokeWidth(size, 0.06)) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round, LineJoin = PenLineJoin.Round };

                // Node, left (ink wash + ink stroke)
                context.DrawEllipse(inkWashBrush, inkPen, new Point(size * 0.190, size * 0.725), size * 0.140, size * 0.140);
                // Node, right (ink wash + ink stroke)
                context.DrawEllipse(inkWashBrush, inkPen, new Point(size * 0.810, size * 0.725), size * 0.140, size * 0.140);

                // Deck (ink)
                context.DrawLine(inkPen, new Point(size * 0.330, size * 0.725), new Point(size * 0.670, size * 0.725));

                // Apex (brand wash + brand stroke)
                var apexGeometry = new PathGeometry();
                var apexFigure = new PathFigure { StartPoint = new Point(size * 0.500, size * 0.085), IsClosed = true };
                apexFigure.Segments.Add(new LineSegment(new Point(size * 0.670, size * 0.430), true));
                apexFigure.Segments.Add(new LineSegment(new Point(size * 0.330, size * 0.430), true));
                apexGeometry.Figures.Add(apexFigure);
                context.DrawGeometry(brandWashBrush, brandPen, apexGeometry);
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
