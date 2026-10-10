using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Windows.Media.Imaging;

namespace RevitBridge.UI
{
    /// <summary>
    /// Loads the embedded brand PNGs (src/UI/Resources/Brand, logical names
    /// "RevitBridge.Brand.cerberus-{size}.png"). Never throws: every failure returns null so the
    /// caller falls back to the generated vector icon. Bitmaps are frozen, so they are safe to
    /// hand to Revit's ribbon and to WPF dialogs on any thread. Keep in sync with docs/design/tokens.md.
    /// </summary>
    internal static class BrandAssets
    {
        private const string ResourcePrefix = "RevitBridge.Brand.cerberus-";
        private static readonly object Gate = new object();
        private static readonly Dictionary<int, BitmapSource?> Cache = new Dictionary<int, BitmapSource?>();

        /// <summary>Embedded sizes: 16/32 for the ribbon, 96/128 for About and dialogs.</summary>
        internal static readonly int[] Sizes = { 16, 32, 96, 128 };

        /// <summary>Returns the frozen colour brand bitmap for an exact embedded size, or null.</summary>
        internal static BitmapSource? TryLoad(int size)
        {
            if (Array.IndexOf(Sizes, size) < 0)
            {
                return null;
            }

            lock (Gate)
            {
                if (Cache.TryGetValue(size, out var cached))
                {
                    return cached;
                }

                BitmapSource? loaded;
                try
                {
                    loaded = Read(size);
                }
                catch
                {
                    loaded = null;
                }

                Cache[size] = loaded;
                return loaded;
            }
        }

        private static BitmapSource? Read(int size)
        {
            var name = ResourcePrefix + size + ".png";
            using (Stream? stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(name))
            {
                if (stream == null)
                {
                    return null;
                }

                var image = new BitmapImage();
                image.BeginInit();
                image.CacheOption = BitmapCacheOption.OnLoad; // decode now so the stream can be disposed
                image.StreamSource = stream;
                image.EndInit();
                image.Freeze();
                return image;
            }
        }
    }
}
