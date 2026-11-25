using System;
using System.Collections.Generic;
using System.Linq;

namespace RevitBridge.Bridge;

/// <summary>Timing figures for one finished request. Null fields were not measured.</summary>
public sealed class RequestTimings
{
    /// <summary>Enqueue to dequeue: waiting in the queue and for Revit's turn.</summary>
    public long? QueuedMs { get; set; }
    /// <summary>The command itself, on the Revit thread.</summary>
    public long? RunMs { get; set; }
    /// <summary>Serializing the response to JSON.</summary>
    public long? SerializeMs { get; set; }
    /// <summary>Size of the serialized response in UTF-8 bytes.</summary>
    public long ResponseBytes { get; set; }
}

/// <summary>Rolling figures for one tool, computed from the last <see cref="ToolTimings.Window"/> runs.</summary>
public sealed class ToolTimingStats
{
    public int Count { get; set; }
    public double P50Ms { get; set; }
    public double P95Ms { get; set; }
    public double MaxMs { get; set; }
    public double AvgBytes { get; set; }
}

/// <summary>
/// Rolling per-tool timings for /health. The milliseconds are run time (the command on the Revit thread),
/// not queue wait or serialization, so a busy queue does not make a fast tool look slow.
/// Kept free of Revit types so packages/revit-bridge-addin-tests can test it. Thread-safe.
/// </summary>
public sealed class ToolTimings
{
    public const int Window = 200;

    private sealed class Ring
    {
        public readonly long[] Ms = new long[Window];
        public readonly long[] Bytes = new long[Window];
        public int Next;
        public int Filled;
    }

    private readonly object _sync = new();
    private readonly Dictionary<string, Ring> _tools = new(StringComparer.Ordinal);

    public void Record(string tool, long runMs, long responseBytes)
    {
        if (string.IsNullOrEmpty(tool)) return;
        lock (_sync)
        {
            if (!_tools.TryGetValue(tool, out var ring))
            {
                ring = new Ring();
                _tools[tool] = ring;
            }
            ring.Ms[ring.Next] = Math.Max(0, runMs);
            ring.Bytes[ring.Next] = Math.Max(0, responseBytes);
            ring.Next = (ring.Next + 1) % Window;
            if (ring.Filled < Window) ring.Filled++;
        }
    }

    public SortedDictionary<string, ToolTimingStats> Snapshot()
    {
        var result = new SortedDictionary<string, ToolTimingStats>(StringComparer.Ordinal);
        lock (_sync)
        {
            foreach (var pair in _tools)
            {
                var ring = pair.Value;
                if (ring.Filled == 0) continue;
                var ms = new long[ring.Filled];
                Array.Copy(ring.Ms, ms, ring.Filled);
                Array.Sort(ms);
                long bytes = 0;
                for (var i = 0; i < ring.Filled; i++) bytes += ring.Bytes[i];
                result[pair.Key] = new ToolTimingStats
                {
                    Count = ring.Filled,
                    P50Ms = Percentile(ms, 50),
                    P95Ms = Percentile(ms, 95),
                    MaxMs = ms[ms.Length - 1],
                    AvgBytes = Math.Round((double)bytes / ring.Filled, 1)
                };
            }
        }
        return result;
    }

    /// <summary>The /health shape: {"tool": {"count", "p50_ms", "p95_ms", "max_ms", "avg_bytes"}}.</summary>
    public Dictionary<string, object> ToHealth()
    {
        return Snapshot().ToDictionary(
            pair => pair.Key,
            pair => (object)new
            {
                count = pair.Value.Count,
                p50_ms = pair.Value.P50Ms,
                p95_ms = pair.Value.P95Ms,
                max_ms = pair.Value.MaxMs,
                avg_bytes = pair.Value.AvgBytes
            },
            StringComparer.Ordinal);
    }

    /// <summary>Nearest-rank percentile of an ascending array (not empty).</summary>
    internal static double Percentile(long[] sorted, int percent)
    {
        var rank = (int)Math.Ceiling(percent / 100.0 * sorted.Length);
        var index = Math.Min(sorted.Length - 1, Math.Max(0, rank - 1));
        return sorted[index];
    }
}
