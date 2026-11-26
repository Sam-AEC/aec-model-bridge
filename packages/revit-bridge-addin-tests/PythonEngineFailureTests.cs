using System;
using RevitBridge.Bridge;
using Xunit;

namespace RevitBridge.Tests;

public class PythonEngineFailureTests
{
    [Fact]
    public void Names_the_exception_type_when_the_message_is_a_bare_word()
    {
        var text = PythonEngineFailure.Describe(new Exception("Error"));
        Assert.Contains("Exception: Error", text);
        Assert.StartsWith("The Python engine could not start.", text);
    }

    [Fact]
    public void Follows_inner_exceptions_to_the_real_cause()
    {
        var inner = new ArgumentException("Type does not have a method with a given name and signature.");
        var text = PythonEngineFailure.Describe(new Exception("Error", inner));
        Assert.Contains("Exception: Error <- ArgumentException: Type does not have a method", text);
    }

    [Fact]
    public void Output_is_ascii_without_line_breaks_and_bounded()
    {
        var text = PythonEngineFailure.Describe(new InvalidOperationException("café\r\nline" + new string('x', 5000)));
        foreach (var ch in text) Assert.InRange(ch, ' ', '~');
        Assert.True(text.Length <= 800);
    }

    [Fact]
    public void Unavailable_runtime_reports_the_host_and_the_engine_state()
    {
        var runtime = PythonEngineFailure.Unavailable();
        var type = runtime.GetType();
        Assert.Equal(false, type.GetProperty("available")!.GetValue(runtime));
        Assert.False(string.IsNullOrWhiteSpace((string?)type.GetProperty("host_runtime")!.GetValue(runtime)));
        Assert.Equal("engine_unavailable", PythonEngineFailure.EngineUnavailableKind);
    }
}
