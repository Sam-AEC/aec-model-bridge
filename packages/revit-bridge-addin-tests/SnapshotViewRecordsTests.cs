using System.Collections.Generic;
using System.Linq;
using RevitBridge.Bridge;
using Xunit;

namespace RevitBridge.Tests;

public class SnapshotViewRecordsTests
{
    [Theory]
    [InlineData("FloorPlan")]
    [InlineData("Section")]
    [InlineData("ThreeD")]
    [InlineData("DraftingView")]
    [InlineData("Legend")]
    [InlineData("Schedule")]
    public void Placeable_view_types_are_captured(string type)
        => Assert.True(SnapshotViewRecords.IsCapturableViewType(type));

    [Theory]
    [InlineData("DrawingSheet")]
    [InlineData("ProjectBrowser")]
    [InlineData("SystemBrowser")]
    [InlineData("Internal")]
    [InlineData("Undefined")]
    [InlineData("drawingsheet")]
    [InlineData("")]
    [InlineData(null)]
    public void Sheets_browsers_and_internal_views_are_skipped(string? type)
        => Assert.False(SnapshotViewRecords.IsCapturableViewType(type));

    [Fact]
    public void A_view_placed_on_a_sheet_links_both_ways()
    {
        var map = new SnapshotViewRecords.PlacementMap();
        map.Add("s1", "v1");
        Assert.Equal("s1", map.SheetOf("v1"));
        Assert.Equal(new[] { "v1" }, map.ViewUidsOn("s1"));
    }

    [Fact]
    public void A_view_on_no_sheet_has_no_sheet_uid_and_an_empty_sheet_has_no_views()
    {
        var map = new SnapshotViewRecords.PlacementMap();
        map.Add("s1", "v1");
        Assert.Null(map.SheetOf("v2"));
        Assert.Empty(map.ViewUidsOn("s2"));
    }

    [Fact]
    public void Duplicate_and_blank_links_are_ignored()
    {
        var map = new SnapshotViewRecords.PlacementMap();
        map.Add("s1", "v1");
        map.Add("s1", "v1");
        map.Add("", "v2");
        map.Add("s1", null);
        Assert.Equal(1, map.LinkCount);
        Assert.Equal(new[] { "v1" }, map.ViewUidsOn("s1"));
    }

    [Fact]
    public void A_view_on_two_sheets_keeps_the_first_sheet_and_appears_on_both()
    {
        var map = new SnapshotViewRecords.PlacementMap();
        map.Add("s1", "legend");
        map.Add("s2", "legend");
        Assert.Equal("s1", map.SheetOf("legend"));
        Assert.Contains("legend", map.ViewUidsOn("s2"));
    }

    [Fact]
    public void View_record_has_exactly_the_documented_keys()
    {
        var rec = SnapshotViewRecords.BuildView("v1", "Level 1", "FloorPlan", false, "s1", "Architectural");
        Assert.Equal(
            new[] { "discipline", "is_template", "name", "sheet_uid", "uid", "view_type" },
            rec.Keys.OrderBy(k => k).ToArray());
        Assert.Equal("s1", rec["sheet_uid"]);
        Assert.Equal(false, rec["is_template"]);
    }

    [Fact]
    public void Unplaced_view_serializes_sheet_uid_as_null_and_null_text_as_empty()
    {
        var rec = SnapshotViewRecords.BuildView("v2", null, "Section", false, null, null);
        Assert.Null(rec["sheet_uid"]);
        Assert.Equal("", rec["name"]);
        Assert.Equal("", rec["discipline"]);
        Assert.True(rec.ContainsKey("sheet_uid"));
    }

    [Fact]
    public void Template_is_flagged_and_never_claims_a_sheet()
    {
        var rec = SnapshotViewRecords.BuildView("t1", "Tmpl", "FloorPlan", true, "s1", null);
        Assert.Equal(true, rec["is_template"]);
        Assert.Null(rec["sheet_uid"]);
    }

    [Fact]
    public void Sheet_record_has_exactly_the_documented_keys()
    {
        var rec = SnapshotViewRecords.BuildSheet("s1", "A-101", "Plan", new[] { "v1", "v2" }, null);
        Assert.Equal(
            new[] { "name", "number", "params", "uid", "view_uids" },
            rec.Keys.OrderBy(k => k).ToArray());
        Assert.Equal(new[] { "v1", "v2" }, (List<string>)rec["view_uids"]!);
        Assert.NotNull(rec["params"]);
    }

    [Fact]
    public void Sheet_without_views_has_an_empty_view_uids_list_not_a_missing_key()
    {
        var rec = SnapshotViewRecords.BuildSheet("s2", null, null, new string[0], null);
        Assert.Empty((List<string>)rec["view_uids"]!);
        Assert.Equal("", rec["number"]);
    }
}
