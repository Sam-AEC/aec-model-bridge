using System;
using System.Collections.Generic;
using System.Text.Json;
using RevitBridge.Bridge;
using Xunit;

namespace RevitBridge.Tests;

public class SnapshotExtraRecordsTests
{
    [Fact]
    public void No_include_means_no_optional_blocks()
    {
        var none = SnapshotExtraRecords.Parse(null);
        Assert.False(none.Any);
        Assert.Empty(none.Names());
        Assert.False(SnapshotExtraRecords.Parse(new string?[0]).Any);
    }

    [Fact]
    public void Names_are_trimmed_case_folded_deduplicated_and_ordered()
    {
        var sel = SnapshotExtraRecords.Parse(new string?[] { " ROOMS ", "Types", "rooms" });
        Assert.True(sel.Types);
        Assert.True(sel.Rooms);
        Assert.False(sel.Cad);
        Assert.Equal(new[] { "types", "rooms" }, sel.Names());
    }

    [Theory]
    [InlineData("views")]
    [InlineData("")]
    [InlineData(null)]
    public void An_unknown_or_empty_block_name_is_refused(string? name)
    {
        var ex = Assert.Throws<ArgumentException>(() => SnapshotExtraRecords.Parse(new[] { name }));
        Assert.Contains("types, cad, rooms", ex.Message);
    }

    [Fact]
    public void A_type_record_carries_the_keys_the_server_reads()
    {
        var t = SnapshotExtraRecords.BuildType("123", "OST_Doors", "Single-Flush", "0915 x 2134", "loadable", 7);
        Assert.Equal("123", t["uid"]);
        Assert.Equal("OST_Doors", t["category"]);
        Assert.Equal("Single-Flush", t["family"]);
        Assert.Equal("0915 x 2134", t["type_name"]);
        Assert.Equal("loadable", t["family_source"]);
        Assert.Equal(7, t["instance_count"]);
        Assert.True(t.ContainsKey("params"));
    }

    [Theory]
    [InlineData("system", "system")]
    [InlineData("INPLACE", "inplace")]
    [InlineData(" loadable ", "loadable")]
    [InlineData("anything else", "loadable")]
    [InlineData(null, "loadable")]
    public void Family_source_is_one_of_three_values(string? given, string expected)
        => Assert.Equal(expected, SnapshotExtraRecords.NormalizeFamilySource(given));

    [Fact]
    public void Missing_text_and_negative_counts_do_not_leak_into_a_type_record()
    {
        var t = SnapshotExtraRecords.BuildType("9", null, null, null, "system", -3);
        Assert.Equal("None", t["category"]);
        Assert.Equal(string.Empty, t["family"]);
        Assert.Equal(string.Empty, t["type_name"]);
        Assert.Equal(0, t["instance_count"]);
    }

    [Fact]
    public void A_cad_record_says_whether_it_is_a_link_and_whether_it_is_view_specific()
    {
        var c = SnapshotExtraRecords.BuildCad(55, "site.dwg", false, true);
        Assert.Equal(55L, c["element_id"]);
        Assert.Equal("site.dwg", c["name"]);
        Assert.Equal(false, c["is_link"]);
        Assert.Equal(true, c["view_specific"]);
        Assert.Equal("(unnamed CAD)", SnapshotExtraRecords.BuildCad(1, "  ", true, false)["name"]);
    }

    [Fact]
    public void A_room_reference_is_a_string_parameter_and_empty_means_no_room()
    {
        var some = SnapshotExtraRecords.BuildRoomRefParam("room-uid");
        Assert.Equal("room-uid", some["v"]);
        Assert.Equal("String", some["storage"]);
        Assert.Equal(true, some["readonly"]);
        Assert.Equal(string.Empty, SnapshotExtraRecords.BuildRoomRefParam(null)["v"]);
    }

    [Fact]
    public void Records_serialize_to_the_json_shape_the_server_reads()
    {
        var json = JsonSerializer.Serialize(new Dictionary<string, object?>
        {
            ["types"] = new List<object?> { SnapshotExtraRecords.BuildType("1", "OST_Walls", "Basic Wall", "Generic", "system", 2) },
            ["cad_scanned"] = true,
            ["cad"] = new List<object?> { SnapshotExtraRecords.BuildCad(5, "a.dwg", true, false) },
        });
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        Assert.True(root.GetProperty("cad_scanned").GetBoolean());
        Assert.Equal(2, root.GetProperty("types")[0].GetProperty("instance_count").GetInt32());
        Assert.Equal("system", root.GetProperty("types")[0].GetProperty("family_source").GetString());
        Assert.True(root.GetProperty("cad")[0].GetProperty("is_link").GetBoolean());
    }
}
