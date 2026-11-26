using System.Text.Json;
using RevitBridge.Bridge;
using Xunit;

namespace RevitBridge.Tests;

public class HubVersionCheckTests
{
    [Theory]
    [InlineData("1.6.0", "1.6.0", false)]
    [InlineData("1.6.0rc1", "1.6.0", false)]
    [InlineData("1.5.2", "1.6.0", true)]
    [InlineData("1.6.1", "1.6.0", true)]
    [InlineData(null, "1.6.0", true)]
    [InlineData("0+unknown", "1.6.0", true)]
    public void Mismatch_compares_major_minor_patch(string? hub, string addin, bool expected)
    {
        Assert.Equal(expected, HubVersionCheck.IsMismatch(hub, addin));
    }

    [Fact]
    public void Apply_adds_a_failing_check_for_an_old_hub()
    {
        using var doc = JsonDocument.Parse("{\"ok\":true,\"hub_version\":\"1.5.0\",\"checks\":[{\"id\":\"hub\",\"ok\":true}]}");
        var result = HubVersionCheck.Apply(doc.RootElement, "1.6.0");

        Assert.False(result.GetProperty("ok").GetBoolean());
        var checks = result.GetProperty("checks");
        Assert.Equal(2, checks.GetArrayLength());
        Assert.Equal("hub_version", checks[1].GetProperty("id").GetString());
        Assert.False(checks[1].GetProperty("ok").GetBoolean());
        Assert.Contains("1.5.0", checks[1].GetProperty("detail").GetString());
    }

    [Fact]
    public void Apply_flags_a_hub_that_reports_no_version()
    {
        using var doc = JsonDocument.Parse("{\"ok\":true,\"checks\":[]}");
        var result = HubVersionCheck.Apply(doc.RootElement, "1.6.0");
        Assert.Equal(1, result.GetProperty("checks").GetArrayLength());
    }

    [Fact]
    public void Apply_leaves_a_matching_hub_alone()
    {
        using var doc = JsonDocument.Parse("{\"ok\":true,\"hub_version\":\"1.6.0\",\"checks\":[]}");
        var result = HubVersionCheck.Apply(doc.RootElement, "1.6.0");
        Assert.True(result.GetProperty("ok").GetBoolean());
        Assert.Equal(0, result.GetProperty("checks").GetArrayLength());
    }
}
