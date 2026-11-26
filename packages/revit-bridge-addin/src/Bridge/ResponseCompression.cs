using System;
using System.IO;
using System.IO.Compression;

namespace RevitBridge.Bridge;

/// <summary>
/// gzip for large bridge responses. No Revit types here, so packages/revit-bridge-addin-tests can
/// cover it. Only bodies over <see cref="MinBytes"/> are compressed, and only when the client sent
/// Accept-Encoding with gzip (q above 0). Small responses stay plain.
/// </summary>
internal static class ResponseCompression
{
    public const int MinBytes = 64 * 1024;

    /// <summary>True when <paramref name="acceptEncoding"/> allows gzip and the body is over MinBytes.</summary>
    public static bool ShouldGzip(string? acceptEncoding, int bodyBytes)
    {
        return bodyBytes > MinBytes && AcceptsGzip(acceptEncoding);
    }

    /// <summary>Parses an Accept-Encoding header: "gzip", "gzip;q=0.5", "br, gzip". "gzip;q=0" is a refusal.</summary>
    public static bool AcceptsGzip(string? acceptEncoding)
    {
        if (string.IsNullOrWhiteSpace(acceptEncoding)) return false;

        foreach (var part in acceptEncoding!.Split(','))
        {
            var pieces = part.Split(';');
            var coding = pieces[0].Trim();
            if (!string.Equals(coding, "gzip", StringComparison.OrdinalIgnoreCase)) continue;

            for (var i = 1; i < pieces.Length; i++)
            {
                var param = pieces[i].Trim();
                if (param.StartsWith("q=", StringComparison.OrdinalIgnoreCase)
                    && double.TryParse(param.Substring(2), System.Globalization.NumberStyles.Float,
                        System.Globalization.CultureInfo.InvariantCulture, out var q)
                    && q <= 0)
                {
                    return false;
                }
            }

            return true;
        }

        return false;
    }

    // CompressionMode (not CompressionLevel) keeps net48 on System.dll alone.
    public static byte[] Gzip(byte[] body)
    {
        if (body == null) throw new ArgumentNullException(nameof(body));
        using var output = new MemoryStream();
        using (var gzip = new GZipStream(output, CompressionMode.Compress, leaveOpen: true))
        {
            gzip.Write(body, 0, body.Length);
        }

        return output.ToArray();
    }
}
