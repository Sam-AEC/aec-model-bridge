using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace RevitBridge.UI
{
    /// <summary>
    /// The AEC Model Bridge app mark: an isometric model cube with a bridge arch cut
    /// through each side face, on a dark tile. One drawing, shared by the ribbon brand
    /// icon, the dialog header and the About/brand cards. Mirrors assets/logo-mark.svg
    /// (96 x 96 design space). Keep in sync with docs/design/tokens.md.
    /// </summary>
    internal static class BrandMark
    {
        private const string TopFace = "M48,16 L76,32 L48,48 L20,32 Z";
        private const string LeftFace = "M20,32 L48,48 L48,80 L20,64 Z";
        private const string RightFace = "M48,48 L76,32 L76,64 L48,80 Z";
        // Unit arch, mapped onto each side face by an affine matrix.
        private const string Arch = "M0.24,1.02 L0.24,0.66 A0.26,0.26 0 0 1 0.76,0.66 L0.76,1.02 Z";

        private static readonly Color TileColor = Color.FromRgb(0x11, 0x19, 0x23);
        private static readonly Color TopColor = Color.FromRgb(0x1C, 0xB5, 0xCA);
        private static readonly Color LeftColor = Color.FromRgb(0xFF, 0xFF, 0xFF);
        private static readonly Color RightColor = Color.FromRgb(0xAE, 0xBC, 0xCB);

        /// <summary>Draws the tile and mark into a 0..96 design space.</summary>
        public static void Draw(DrawingContext context, bool arches = true)
        {
            var tile = new SolidColorBrush(TileColor);
            var seam = new Pen(tile, 2.5) { LineJoin = PenLineJoin.Round };

            context.DrawRoundedRectangle(tile, null, new Rect(0, 0, 96, 96), arches ? 20 : 14, arches ? 20 : 14);
            context.DrawGeometry(new SolidColorBrush(TopColor), seam, Geometry.Parse(TopFace));
            context.DrawGeometry(new SolidColorBrush(LeftColor), seam, Geometry.Parse(LeftFace));
            context.DrawGeometry(new SolidColorBrush(RightColor), seam, Geometry.Parse(RightFace));

            if (!arches)
            {
                return;
            }

            var arch = Geometry.Parse(Arch);
            context.PushTransform(new MatrixTransform(28, 16, 0, 32, 20, 32));
            context.DrawGeometry(tile, null, arch);
            context.Pop();
            context.PushTransform(new MatrixTransform(28, -16, 0, 32, 48, 48));
            context.DrawGeometry(tile, null, arch);
            context.Pop();
        }

        public static ImageSource CreateImageSource(bool arches = true)
        {
            var group = new DrawingGroup();
            using (var context = group.Open())
            {
                Draw(context, arches);
            }

            var image = new DrawingImage(group);
            image.Freeze();
            return image;
        }

        public static Image CreateImage(double size)
        {
            return new Image
            {
                Source = CreateImageSource(),
                Width = size,
                Height = size,
                Stretch = Stretch.Uniform,
                VerticalAlignment = VerticalAlignment.Center,
                HorizontalAlignment = HorizontalAlignment.Center,
                SnapsToDevicePixels = true
            };
        }
    }
}
