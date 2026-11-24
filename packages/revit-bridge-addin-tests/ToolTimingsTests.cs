using System;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using RevitBridge.Bridge;
using Xunit;

namespace RevitBridge.Tests;

public class ToolTimingsTests
{
    [Fact]
    public void Percentiles_max_and_average_bytes_per_tool()
    {
        var timings = new ToolTimings();
        for (var ms = 1; ms <= 100; ms++) timings.Record("revit.list_levels", ms, 1000);
        timings.Record("revit.get_context", 7, 50);

        var stats = timings.Snapshot();
        var levels = stats["revit.list_levels"];
        Assert.Equal(100, levels.Count);
        Assert.Equal(50, levels.P50Ms);
        Assert.Equal(95, levels.P95Ms);
        Assert.Equal(100, levels.MaxMs);
        Assert.Equal(1000, levels.AvgBytes);
        Assert.Equal(1, stats["revit.get_context"].Count);
        Assert.Equal(7, stats["revit.get_context"].P95Ms);
    }

    [Fact]
    public void Only_the_last_200_runs_count()
    {
        var timings = new ToolTimings();
        for (var i = 0; i < 300; i++) timings.Record("t", i < 100 ? 10000 : 5, 10);
        var stats = timings.Snapshot()["t"];
        Assert.Equal(ToolTimings.Window, stats.Count);
        Assert.Equal(5, stats.MaxMs);
    }

    [Fact]
    public void Health_shape_matches_what_the_python_client_reads()
    {
        var timings = new ToolTimings();
        timings.Record("revit.list_levels", 12, 345);
        using var doc = JsonDocument.Parse(JsonSerializer.Serialize(timings.ToHealth()));
        var entry = doc.RootElement.GetProperty("revit.list_levels");
        Assert.Equal(new[] { "count", "p50_ms", "p95_ms", "max_ms", "avg_bytes" },
            entry.EnumerateObject().Select(p => p.Name).ToArray());
        Assert.Equal(1, entry.GetProperty("count").GetInt32());
        Assert.Equal(12, entry.GetProperty("p50_ms").GetDouble());
        Assert.Equal(345, entry.GetProperty("avg_bytes").GetDouble());
    }

    [Fact]
    public void Recording_from_many_threads_loses_nothing()
    {
        var timings = new ToolTimings();
        Parallel.For(0, 1000, i => timings.Record("tool" + (i % 4), i % 50, 1));
        var stats = timings.Snapshot();
        Assert.Equal(4, stats.Count);
        Assert.All(stats.Values, s => Assert.Equal(ToolTimings.Window, s.Count));
    }

    [Fact]
    public void Queue_records_timings_for_requests_that_ran_but_not_for_abandoned_ones()
    {
        var q = new CommandQueue(TimeSpan.FromSeconds(900), TimeSpan.FromSeconds(120), 500, 64L * 1024 * 1024, () => DateTime.UtcNow);
        q.Enqueue(new CommandRequest { RequestId = "a", Tool = "revit.list_levels", Payload = Json.Parse("{}") });
        q.Enqueue(new CommandRequest { RequestId = "b", Tool = "revit.list_views", Payload = Json.Parse("{}") });
        q.TryDequeue(out _);
        q.MarkRunning("a");
        q.Complete("a", new CommandResponse { Status = "ok", Tool = "revit.list_levels", Result = new { levels = new[] { "L1" } } });
        q.TryDequeue(out _);
        q.Complete("b", new CommandResponse { Status = "error", Tool = "revit.list_views", Message = "Abandoned before it started" });

        var ran = q.GetSnapshot("a")!.Timings;
        Assert.NotNull(ran);
        Assert.True(ran!.QueuedMs >= 0 && ran.RunMs >= 0 && ran.SerializeMs >= 0);
        Assert.Equal(System.Text.Encoding.UTF8.GetByteCount(q.GetSnapshot("a")!.ResponseJson!), ran.ResponseBytes);
        Assert.Null(q.GetSnapshot("b")!.Timings);

        var stats = q.Timings.Snapshot();
        Assert.Equal(new[] { "revit.list_levels" }, stats.Keys.ToArray());
    }

    [Fact]
    public void TryDequeueIf_leaves_a_refused_request_at_the_head()
    {
        var q = new CommandQueue();
        q.Enqueue(new CommandRequest { RequestId = "w", Tool = "revit.create_wall", Payload = Json.Parse("{}") });
        q.Enqueue(new CommandRequest { RequestId = "r", Tool = "revit.list_levels", Payload = Json.Parse("{}") });
        Assert.False(q.TryDequeueIf(r => r.Tool == "revit.list_levels", out var none));
        Assert.Null(none);
        Assert.Equal(2, q.Count);
        Assert.True(q.TryDequeue(out var first));
        Assert.Equal("w", first!.RequestId);
        Assert.True(q.TryDequeueIf(r => r.Tool == "revit.list_levels", out var read));
        Assert.Equal("r", read!.RequestId);
    }
}
