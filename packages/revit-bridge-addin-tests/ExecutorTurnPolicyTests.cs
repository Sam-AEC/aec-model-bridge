using System;
using System.IO;
using System.Text;
using RevitBridge.Bridge;
using Xunit;

namespace RevitBridge.Tests;

public class ExecutorTurnPolicyTests
{
    private static bool ReadOnly(string tool) => tool.StartsWith("revit.list_", StringComparison.Ordinal)
        || tool.StartsWith("revit.export_", StringComparison.Ordinal)
        || tool == "revit.extract_snapshot";

    [Theory]
    [InlineData(null, 40)]
    [InlineData("", 40)]
    [InlineData("abc", 40)]
    [InlineData("0", 0)]
    [InlineData("25", 25)]
    [InlineData("-5", 0)]
    [InlineData("5000", 200)]
    public void Budget_defaults_to_40_and_is_clamped(string? raw, int expected)
    {
        Assert.Equal(expected, ExecutorTurnPolicy.ParseBudgetMs(raw));
    }

    [Theory]
    [InlineData(null, false)]
    [InlineData("0", false)]
    [InlineData("yes", false)]
    [InlineData("1", true)]
    [InlineData("TRUE", true)]
    public void Fast_wake_is_off_unless_asked_for(string? raw, bool expected)
    {
        Assert.Equal(expected, ExecutorTurnPolicy.ParseFastWake(raw));
    }

    [Theory]
    [InlineData("revit.list_levels", true)]
    [InlineData("revit.create_wall", false)]
    [InlineData("revit.not_a_command", false)]
    [InlineData("", false)]
    [InlineData(null, false)]
    [InlineData("revit.export_pdf_by_sheet_set", false)]
    [InlineData("revit.extract_snapshot", false)]
    public void Only_quick_read_only_commands_may_share_a_turn(string? tool, bool expected)
    {
        Assert.Equal(expected, ExecutorTurnPolicy.MayShareTurn(tool, ReadOnly));
    }

    [Fact]
    public void Writes_never_share_a_turn()
    {
        // The first request always runs; after a write nothing else joins, whatever the budget.
        Assert.True(ExecutorTurnPolicy.MayTakeAnother(0, true, 0, 0));
        Assert.False(ExecutorTurnPolicy.MayTakeAnother(1, false, 0, 200));
        Assert.False(ExecutorTurnPolicy.MayShareTurn("revit.create_wall", ReadOnly));
    }

    [Fact]
    public void Reads_share_a_turn_only_inside_the_budget()
    {
        Assert.True(ExecutorTurnPolicy.MayTakeAnother(1, true, 39, 40));
        Assert.False(ExecutorTurnPolicy.MayTakeAnother(1, true, 40, 40));
        Assert.False(ExecutorTurnPolicy.MayTakeAnother(3, true, 1, 0)); // budget 0: one request per turn
    }

    [Fact]
    public void Fast_wake_is_attached_only_while_work_is_queued()
    {
        var gate = new FastWakeGate(enabled: true);
        Assert.False(gate.ShouldAttach(0));
        Assert.True(gate.ShouldAttach(2));
        Assert.True(gate.Attached);
        Assert.False(gate.ShouldAttach(1)); // already attached
        Assert.False(gate.ShouldDetach(1));
        Assert.True(gate.ShouldDetach(0));
        Assert.False(gate.Attached);
        Assert.False(gate.ShouldDetach(0));
    }

    [Fact]
    public void Fast_wake_never_attaches_when_off()
    {
        var gate = new FastWakeGate(enabled: false);
        Assert.False(gate.ShouldAttach(5));
        Assert.False(gate.Attached);
    }
}

public class PythonEngineReusePolicyTests
{
    [Theory]
    [InlineData(null, 50)]
    [InlineData("x", 50)]
    [InlineData("0", 1)]
    [InlineData("10", 10)]
    [InlineData("999999", 10000)]
    public void Recycle_runs_default_to_50_and_are_clamped(string? raw, int expected)
    {
        Assert.Equal(expected, PythonEngineReusePolicy.ParseRecycleRuns(raw));
    }

    [Fact]
    public void Engine_is_reused_until_the_run_limit_or_a_document_change()
    {
        Assert.Null(PythonEngineReusePolicy.RecycleReason(0, 50, "A|c:\\a.rvt", "A|c:\\a.rvt"));
        Assert.Null(PythonEngineReusePolicy.RecycleReason(49, 50, "A|c:\\a.rvt", "A|c:\\a.rvt"));
        Assert.Equal("run_limit", PythonEngineReusePolicy.RecycleReason(50, 50, "A|c:\\a.rvt", "A|c:\\a.rvt"));
        Assert.Equal("document_changed", PythonEngineReusePolicy.RecycleReason(3, 50, "A|c:\\a.rvt", "B|c:\\b.rvt"));
    }

    [Theory]
    [InlineData(null, false)]
    [InlineData("read_mode_violation", true)]
    [InlineData("read_mode_guard_failed", true)]
    [InlineData("transaction_left_open", true)]
    public void Misbehaving_scripts_drop_the_engine(string? kind, bool expected)
    {
        Assert.Equal(expected, PythonEngineReusePolicy.RecycleAfterResult(kind));
    }

    [Fact]
    public void Redirecting_stream_sends_each_run_to_its_own_target()
    {
        var stream = new RedirectingStream();
        var writer = new StreamWriter(stream, new UTF8Encoding(false)) { AutoFlush = true };
        var first = new MemoryStream();
        var second = new MemoryStream();

        stream.Target = first;
        writer.Write("one");
        stream.Target = Stream.Null;
        writer.Write("between runs");
        stream.Target = second;
        writer.Write("two");

        Assert.Equal("one", Encoding.UTF8.GetString(first.ToArray()));
        Assert.Equal("two", Encoding.UTF8.GetString(second.ToArray()));
    }
}
