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
        internal static bool IsDarkTheme()
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

        // ---- Palette (32 px design grid; see docs/design/tokens.md section 5) ----
        private sealed class Palette
        {
            public Brush Ink, Fill, Surface, Face, Accent, Mid, Green, Red, Amber, Ring, OnBadge;
        }

        private static Brush Hex(string hex)
        {
            var brush = new SolidColorBrush((Color)ColorConverter.ConvertFromString(hex));
            brush.Freeze();
            return brush;
        }

        private static Palette GetPalette(bool dark)
        {
            return dark
                ? new Palette
                {
                    Ink = Hex("#E9EEF5"), Fill = Hex("#1F4A55"), Surface = Hex("#252E3A"), Face = Hex("#323D4B"),
                    Accent = Hex("#3FC3D6"), Mid = Hex("#7B8794"), Green = Hex("#3FCB8B"), Red = Hex("#F0796B"),
                    Amber = Hex("#F2A63C"), Ring = Hex("#2B323B"), OnBadge = Hex("#0B1118")
                }
                : new Palette
                {
                    Ink = Hex("#2F3A47"), Fill = Hex("#CFEAF0"), Surface = Hex("#FFFFFF"), Face = Hex("#DDE3E9"),
                    Accent = Hex("#0091A7"), Mid = Hex("#9AA6B2"), Green = Hex("#2E9E4F"), Red = Hex("#D64535"),
                    Amber = Hex("#E39B1B"), Ring = Hex("#FFFFFF"), OnBadge = Hex("#FFFFFF")
                };
        }

        private static Pen P(Brush brush, double width, bool round = true)
        {
            return new Pen(brush, width)
            {
                StartLineCap = round ? PenLineCap.Round : PenLineCap.Flat,
                EndLineCap = round ? PenLineCap.Round : PenLineCap.Flat,
                LineJoin = PenLineJoin.Round
            };
        }

        private static void Shape(DrawingContext c, Brush fill, Pen pen, string path)
        {
            c.DrawGeometry(fill, pen, Geometry.Parse(path));
        }

        /// <summary>Draws in a 32 x 32 grid scaled to the requested pixel size.</summary>
        private static BitmapSource Render32(int size, Action<DrawingContext, Palette> draw)
        {
            var visual = new DrawingVisual();
            using (var context = visual.RenderOpen())
            {
                double scale = size / 32.0;
                context.PushTransform(new ScaleTransform(scale, scale));
                draw(context, GetPalette(IsDarkTheme()));
                context.Pop();
            }

            return RenderVisual(visual, size, size);
        }

        /// <summary>State badge, lower right: 14 px circle with a ring.</summary>
        private static void Badge(DrawingContext c, Palette p, Brush color)
        {
            c.DrawEllipse(color, P(p.Ring, 1.5), new Point(23, 23), 7, 7);
        }

        // ---- Ribbon icons ----
        // The icon PNGs (scripts/make_ribbon_icons.py, docs/RIBBON_ICONS.md) are embedded as
        // RevitBridge.RibbonIcons.<name>_<16|32>_<light|dark>.png; the vector drawings below are the fallback.

        /// <summary>Embedded cut-slate icon for the current Revit theme, or null when it is not in the assembly.</summary>
        internal static BitmapSource? LoadEmbedded(string name, int size)
        {
            try
            {
                int px = size <= 16 ? 16 : 32;
                string resource = $"RevitBridge.RibbonIcons.{name}_{px}_{(IsDarkTheme() ? "dark" : "light")}.png";
                using (Stream? stream = typeof(IconGenerator).Assembly.GetManifestResourceStream(resource))
                {
                    if (stream == null)
                    {
                        return null;
                    }

                    var decoder = new PngBitmapDecoder(stream, BitmapCreateOptions.PreservePixelFormat, BitmapCacheOption.OnLoad);
                    BitmapSource frame = decoder.Frames[0];
                    frame.Freeze();
                    return frame;
                }
            }
            catch
            {
                return null;
            }
        }


        /// <summary>Connected: two model blocks joined by the accent link, green "run" badge.</summary>
        public static BitmapSource CreateConnectedIcon(int size = 32)
        {
            return LoadEmbedded("connected", size) ?? Render32(size, (c, p) =>
            {
                var ink = P(p.Ink, 2);
                Shape(c, p.Fill, ink, "M4.5,5 H10.5 A1.5,1.5 0 0 1 12,6.5 V14.5 A1.5,1.5 0 0 1 10.5,16 H4.5 A1.5,1.5 0 0 1 3,14.5 V6.5 A1.5,1.5 0 0 1 4.5,5 Z");
                Shape(c, p.Fill, ink, "M21.5,5 H27.5 A1.5,1.5 0 0 1 29,6.5 V14.5 A1.5,1.5 0 0 1 27.5,16 H21.5 A1.5,1.5 0 0 1 20,14.5 V6.5 A1.5,1.5 0 0 1 21.5,5 Z");
                c.DrawLine(P(p.Accent, 3), new Point(12, 10.5), new Point(20, 10.5));
                Badge(c, p, p.Green);
                Shape(c, p.OnBadge, null, "M21.2,19.8 L26.2,23 L21.2,26.2 Z");
            });
        }

        /// <summary>Disconnected: the same blocks with a broken link and a red "stop" badge.</summary>
        public static BitmapSource CreateDisconnectedIcon(int size = 32)
        {
            return LoadEmbedded("disconnected", size) ?? Render32(size, (c, p) =>
            {
                var ink = P(p.Ink, 2);
                Shape(c, p.Face, ink, "M4.5,5 H10.5 A1.5,1.5 0 0 1 12,6.5 V14.5 A1.5,1.5 0 0 1 10.5,16 H4.5 A1.5,1.5 0 0 1 3,14.5 V6.5 A1.5,1.5 0 0 1 4.5,5 Z");
                Shape(c, p.Face, ink, "M21.5,5 H27.5 A1.5,1.5 0 0 1 29,6.5 V14.5 A1.5,1.5 0 0 1 27.5,16 H21.5 A1.5,1.5 0 0 1 20,14.5 V6.5 A1.5,1.5 0 0 1 21.5,5 Z");
                var link = P(p.Mid, 3);
                c.DrawLine(link, new Point(12, 10.5), new Point(14, 10.5));
                c.DrawLine(link, new Point(18, 10.5), new Point(20, 10.5));
                Badge(c, p, p.Red);
                c.DrawRoundedRectangle(p.OnBadge, null, new Rect(19.8, 19.8, 6.4, 6.4), 1, 1);
            });
        }

        /// <summary>Status: monitor with an accent pulse line.</summary>
        public static BitmapSource CreateStatusIcon(int size = 32)
        {
            return LoadEmbedded("status", size) ?? Render32(size, (c, p) =>
            {
                var ink = P(p.Ink, 2);
                c.DrawRoundedRectangle(p.Surface, ink, new Rect(3, 4, 26, 18), 2, 2);
                c.DrawLine(ink, new Point(16, 22), new Point(16, 27));
                c.DrawLine(ink, new Point(10, 27), new Point(22, 27));
                Shape(c, null, P(p.Accent, 2.4), "M6.5,14 H11.5 L14,8 L18,19 L20.5,14 H25.5");
            });
        }

        /// <summary>Settings: gear with an accent hub.</summary>
        public static BitmapSource CreateSettingsIcon(int size = 32)
        {
            return LoadEmbedded("settings", size) ?? Render32(size, (c, p) =>
            {
                for (int i = 0; i < 4; i++)
                {
                    c.PushTransform(new RotateTransform(i * 45, 16, 16));
                    c.DrawRoundedRectangle(p.Ink, null, new Rect(14, 2.5, 4, 6), 1, 1);
                    c.DrawRoundedRectangle(p.Ink, null, new Rect(14, 23.5, 4, 6), 1, 1);
                    c.Pop();
                }

                c.DrawEllipse(p.Surface, P(p.Ink, 2), new Point(16, 16), 9, 9);
                c.DrawEllipse(p.Fill, P(p.Accent, 2.2), new Point(16, 16), 3.6, 3.6);
            });
        }

        /// <summary>Help: filled round with an accent question mark.</summary>
        public static BitmapSource CreateHelpIcon(int size = 32)
        {
            return LoadEmbedded("help", size) ?? Render32(size, (c, p) =>
            {
                c.DrawEllipse(p.Fill, P(p.Ink, 2), new Point(16, 16), 12.5, 12.5);
                Shape(c, null, P(p.Accent, 2.6), "M12.4,12.6 A3.7,3.7 0 1 1 17.8,15.9 C16.5,16.6 16,17.3 16,18.6");
                c.DrawEllipse(p.Accent, null, new Point(16, 22.6), 1.7, 1.7);
            });
        }

        /// <summary>About: filled round with an accent "i".</summary>
        public static BitmapSource CreateAboutIcon(int size = 32)
        {
            return LoadEmbedded("about", size) ?? Render32(size, (c, p) =>
            {
                c.DrawEllipse(p.Fill, P(p.Ink, 2), new Point(16, 16), 12.5, 12.5);
                c.DrawEllipse(p.Accent, null, new Point(16, 10.4), 1.8, 1.8);
                c.DrawLine(P(p.Accent, 2.8), new Point(16, 14.6), new Point(16, 22.6));
            });
        }

        /// <summary>Open Panel: window with an accent docked side panel.</summary>
        public static BitmapSource CreatePanelIcon(int size = 32)
        {
            return LoadEmbedded("panel", size) ?? Render32(size, (c, p) =>
            {
                var ink = P(p.Ink, 2);
                c.DrawRoundedRectangle(p.Surface, ink, new Rect(3, 4, 26, 24), 2, 2);
                Shape(c, p.Accent, ink, "M5,4 H13 V28 H5 A2,2 0 0 1 3,26 V6 A2,2 0 0 1 5,4 Z");
                c.DrawLine(ink, new Point(13, 10), new Point(29, 10));
                var line = P(p.Mid, 2);
                c.DrawLine(line, new Point(17.5, 15.5), new Point(25.5, 15.5));
                c.DrawLine(line, new Point(17.5, 20), new Point(23, 20));
            });
        }

        /// <summary>Health Check: isometric model cube with a green check badge.</summary>
        public static BitmapSource CreateHealthIcon(int size = 32)
        {
            return LoadEmbedded("healthcheck", size) ?? Render32(size, (c, p) =>
            {
                var ink = P(p.Ink, 1.8);
                Shape(c, p.Fill, ink, "M14,2 L25,8 L14,14 L3,8 Z");
                Shape(c, p.Surface, ink, "M3,8 L14,14 L14,26 L3,20 Z");
                Shape(c, p.Face, ink, "M14,14 L25,8 L25,20 L14,26 Z");
                Badge(c, p, p.Green);
                Shape(c, null, P(p.OnBadge, 2.2), "M19.6,23 L22,25.4 L26.2,20.8");
            });
        }

        /// <summary>Approve: checklist page with an amber clock badge.</summary>
        public static BitmapSource CreateApproveIcon(int size = 32)
        {
            return LoadEmbedded("approve", size) ?? Render32(size, (c, p) =>
            {
                var ink = P(p.Ink, 2);
                c.DrawRoundedRectangle(p.Surface, ink, new Rect(4, 3, 19, 25), 2, 2);
                c.DrawLine(ink, new Point(8.5, 9), new Point(18.5, 9));
                c.DrawLine(ink, new Point(8.5, 14), new Point(18.5, 14));
                c.DrawLine(ink, new Point(8.5, 19), new Point(13.5, 19));
                Badge(c, p, p.Amber);
                Shape(c, null, P(p.OnBadge, 2), "M23,19 V23.4 L26,25");
            });
        }

        /// <summary>Reports: document with an accent bar chart.</summary>
        public static BitmapSource CreateReportsIcon(int size = 32)
        {
            return LoadEmbedded("reports", size) ?? Render32(size, (c, p) =>
            {
                c.DrawRoundedRectangle(p.Surface, P(p.Ink, 2), new Rect(6, 3, 20, 26), 2, 2);
                c.DrawLine(P(p.Mid, 2), new Point(10.5, 8.5), new Point(21.5, 8.5));
                c.DrawRoundedRectangle(p.Accent, null, new Rect(10.5, 18, 3.4, 7), 0.5, 0.5);
                c.DrawRoundedRectangle(p.Accent, null, new Rect(15.3, 14, 3.4, 11), 0.5, 0.5);
                c.DrawRoundedRectangle(p.Ink, null, new Rect(20.1, 11, 3.4, 14), 0.5, 0.5);
            });
        }

        /// <summary>
        /// The AEC Model Bridge app tile (the Pier mark). The brand artwork is fixed in both
        /// themes, so it is not palette-driven; at 16 px the arches drop out for legibility.
        /// </summary>
        public static BitmapSource CreateBrandIcon(int size = 32)
        {
            var visual = new DrawingVisual();
            using (var context = visual.RenderOpen())
            {
                double scale = size / 96.0;
                context.PushTransform(new ScaleTransform(scale, scale));
                BrandMark.Draw(context, size > 20);
                context.Pop();
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
    }
}
