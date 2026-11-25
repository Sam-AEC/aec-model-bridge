using System;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace RevitBridge.Bridge;

/// <summary>
/// Frame codec of the named-pipe transport (ADR 0021): a 4-byte little-endian length, then UTF-8 JSON.
/// No Revit types, so packages/revit-bridge-addin-tests links and tests it.
/// </summary>
public static class PipeFraming
{
    // Same limit as BridgeServer.MaxRequestSizeBytes for a request; a response may carry a large result.
    public const int MaxRequestFrameBytes = 5 * 1024 * 1024;
    public const int MaxResponseFrameBytes = 64 * 1024 * 1024;

    public static byte[] Encode(string json, int maxBytes)
    {
        var data = Encoding.UTF8.GetBytes(json);
        if (data.Length > maxBytes)
            throw new InvalidDataException("Frame of " + data.Length + " bytes exceeds the " + maxBytes + "-byte limit.");
        var frame = new byte[4 + data.Length];
        frame[0] = (byte)data.Length;
        frame[1] = (byte)(data.Length >> 8);
        frame[2] = (byte)(data.Length >> 16);
        frame[3] = (byte)(data.Length >> 24);
        Buffer.BlockCopy(data, 0, frame, 4, data.Length);
        return frame;
    }

    /// <summary>
    /// Reads one frame body. Returns null when the stream ends before a whole frame arrives.
    /// Throws InvalidDataException when the declared length is above <paramref name="maxBytes"/>; the body is not read.
    /// </summary>
    public static async Task<byte[]?> ReadFrame(Stream stream, int maxBytes, int timeoutMs, CancellationToken token)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(token);
        timeout.CancelAfter(timeoutMs);
        var header = new byte[4];
        if (!await ReadExact(stream, header, timeout.Token).ConfigureAwait(false)) return null;
        var length = (uint)(header[0] | (header[1] << 8) | (header[2] << 16) | (header[3] << 24));
        if (length > (uint)maxBytes)
            throw new InvalidDataException("Frame of " + length + " bytes exceeds the " + maxBytes + "-byte limit.");
        var body = new byte[length];
        if (!await ReadExact(stream, body, timeout.Token).ConfigureAwait(false)) return null;
        return body;
    }

    public static async Task WriteFrame(Stream stream, string json, CancellationToken token)
    {
        var frame = Encode(json, MaxResponseFrameBytes);
        await stream.WriteAsync(frame, 0, frame.Length, token).ConfigureAwait(false);
        await stream.FlushAsync(token).ConfigureAwait(false);
    }

    private static async Task<bool> ReadExact(Stream stream, byte[] buffer, CancellationToken token)
    {
        var offset = 0;
        while (offset < buffer.Length)
        {
            var read = await stream.ReadAsync(buffer, offset, buffer.Length - offset, token).ConfigureAwait(false);
            if (read == 0) return false;
            offset += read;
        }
        return true;
    }

    /// <summary>Compares the presented Authorization value in time that does not depend on where it differs.</summary>
    public static bool TokenMatches(string? presented, string expected)
    {
        if (presented == null) return false;
        var a = Encoding.UTF8.GetBytes(presented);
        var b = Encoding.UTF8.GetBytes(expected);
        var diff = a.Length ^ b.Length;
        for (var i = 0; i < Math.Min(a.Length, b.Length); i++) diff |= a[i] ^ b[i];
        return diff == 0;
    }
}
