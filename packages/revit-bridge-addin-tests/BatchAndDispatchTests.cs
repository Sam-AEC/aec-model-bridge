using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;
using System.Text.Json;
using RevitBridge.Bridge;
using Xunit;

namespace RevitBridge.Tests;

public class BridgeBatchTests
{
    private static readonly HashSet<string> ReadOnly = new() { "revit.list_levels", "revit.get_document_info", "revit.get_element_geometry" };

    private static List<BridgeBatchMember> Parse(string json) => BridgeBatch.Parse(Json.Parse(json), ReadOnly.Contains);

    [Fact]
    public void Read_only_members_are_returned_in_order_with_their_payloads()
    {
        var members = Parse("{\"commands\": [{\"tool\": \"revit.list_levels\"}, {\"tool\": \"revit.get_element_geometry\", \"payload\": {\"element_id\": 7}}]}");
        Assert.Equal(new[] { "revit.list_levels", "revit.get_element_geometry" }, members.Select(m => m.Tool));
        Assert.Equal(new[] { 0, 1 }, members.Select(m => m.Index));
        Assert.Equal(JsonValueKind.Object, members[0].Payload.ValueKind);
        Assert.Equal(7, members[1].Payload.GetProperty("element_id").GetInt32());
    }

    [Fact]
    public void A_mutating_or_unknown_member_refuses_the_whole_batch()
    {
        var ex = Assert.Throws<ArgumentException>(() => Parse("{\"commands\": [{\"tool\": \"revit.list_levels\"}, {\"tool\": \"revit.create_wall\"}]}"));
        Assert.Contains("revit.create_wall", ex.Message);
        Assert.Contains("not a read-only command", ex.Message);
        Assert.Throws<ArgumentException>(() => Parse("{\"commands\": [{\"tool\": \"revit.no_such_command\"}]}"));
    }

    [Theory]
    [InlineData("revit.export_schedules")]
    [InlineData("revit.export_image")]
    [InlineData("revit.extract_snapshot")]
    [InlineData("revit.get_snapshot_delta")]
    [InlineData("revit.select_by_unique_ids")]
    [InlineData("revit.preview_elements")]
    [InlineData("revit.clear_preview")]
    public void Side_effect_commands_are_refused_even_when_the_lookup_says_read_only(string tool)
    {
        Assert.True(BridgeBatch.HasSideEffects(tool));
        var ex = Assert.Throws<ArgumentException>(() =>
            BridgeBatch.Parse(Json.Parse("{\"commands\": [{\"tool\": \"revit.list_levels\"}, {\"tool\": \"" + tool + "\"}]}"), _ => true));
        Assert.Contains(tool, ex.Message);
        Assert.False(BridgeBatch.HasSideEffects("revit.list_levels"));
    }

    [Fact]
    public void Nesting_is_refused_even_when_the_lookup_says_read_only()
    {
        var ex = Assert.Throws<ArgumentException>(() =>
            BridgeBatch.Parse(Json.Parse("{\"commands\": [{\"tool\": \"revit.batch\", \"payload\": {\"commands\": []}}]}"), _ => true));
        Assert.Contains("nested", ex.Message);
    }

    [Fact]
    public void The_batch_size_is_capped()
    {
        var items = string.Join(",", Enumerable.Repeat("{\"tool\": \"revit.list_levels\"}", BridgeBatch.MaxCommands + 1));
        var ex = Assert.Throws<ArgumentException>(() => Parse("{\"commands\": [" + items + "]}"));
        Assert.Contains("at most 25", ex.Message);

        var full = string.Join(",", Enumerable.Repeat("{\"tool\": \"revit.list_levels\"}", BridgeBatch.MaxCommands));
        Assert.Equal(BridgeBatch.MaxCommands, Parse("{\"commands\": [" + full + "]}").Count);
    }

    [Theory]
    [InlineData("{}")]
    [InlineData("{\"commands\": {}}")]
    [InlineData("{\"commands\": []}")]
    [InlineData("{\"commands\": [5]}")]
    [InlineData("{\"commands\": [{\"payload\": {}}]}")]
    [InlineData("{\"commands\": [{\"tool\": \"revit.list_levels\", \"payload\": [1]}]}")]
    [InlineData("[]")]
    public void Bad_shapes_are_refused(string json)
    {
        Assert.Throws<ArgumentException>(() => Parse(json));
    }

    [Fact]
    public void Paths_inside_member_payloads_reach_the_workspace_check()
    {
        var seen = new List<string>();
        PayloadPathValidator.Validate(Json.Parse("{\"commands\": [{\"tool\": \"revit.export_schedules\", \"payload\": {\"output_path\": \"C:\\\\out\"}}]}"), seen.Add);
        Assert.Equal(new[] { "C:\\out" }, seen);
    }
}

public class BridgeDispatchTableTests
{
    private static KeyValuePair<string, int> E(string name, int value) => new(name, value);

    [Fact]
    public void Builds_a_lookup_from_names()
    {
        var table = BridgeDispatchTable.Build(new[] { E("revit.a", 1), E("revit.b", 2) });
        Assert.Equal(2, table.Count);
        Assert.True(table.TryGetValue("revit.b", out var value));
        Assert.Equal(2, value);
        Assert.False(table.ContainsKey("REVIT.B"));
    }

    [Fact]
    public void A_duplicate_name_fails_with_the_name()
    {
        var ex = Assert.Throws<InvalidOperationException>(() => BridgeDispatchTable.Build(new[] { E("revit.a", 1), E("revit.a", 2) }));
        Assert.Contains("revit.a", ex.Message);
    }

    [Fact]
    public void A_blank_name_fails()
    {
        Assert.Throws<InvalidOperationException>(() => BridgeDispatchTable.Build(new[] { E(" ", 1) }));
    }

    [Fact]
    public void Every_addin_command_name_is_unique_in_source()
    {
        // Same rule as the startup check, over the real sources, so a duplicate fails here before Revit loads it.
        var root = typeof(BridgeDispatchTableTests).Assembly
            .GetCustomAttributes(typeof(System.Reflection.AssemblyMetadataAttribute), false)
            .Cast<System.Reflection.AssemblyMetadataAttribute>()
            .FirstOrDefault(a => a.Key == "RepoRoot")?.Value;
        Assert.False(string.IsNullOrEmpty(root), "RepoRoot metadata missing from the test assembly");
        var src = Path.Combine(root!, "packages", "revit-bridge-addin", "src");
        var pattern = new System.Text.RegularExpressions.Regex("\\[BridgeCommand\\(\\s*\"([^\"]+)\"");
        var names = Directory.EnumerateFiles(src, "*.cs", SearchOption.AllDirectories)
            .SelectMany(file => pattern.Matches(File.ReadAllText(file)).Cast<System.Text.RegularExpressions.Match>())
            .Select(match => new KeyValuePair<string, int>(match.Groups[1].Value, 0))
            .ToList();
        Assert.NotEmpty(names);
        BridgeDispatchTable.Build(names);
    }
}

public class ResponseCompressionTests
{
    [Theory]
    [InlineData("gzip", true)]
    [InlineData("gzip, deflate, br", true)]
    [InlineData("br;q=1.0, GZIP;q=0.5", true)]
    [InlineData("gzip;q=0", false)]
    [InlineData("deflate", false)]
    [InlineData("", false)]
    [InlineData(null, false)]
    public void Accept_encoding_is_parsed(string? header, bool expected)
    {
        Assert.Equal(expected, ResponseCompression.AcceptsGzip(header));
    }

    [Fact]
    public void Only_bodies_over_64_KB_are_compressed()
    {
        Assert.False(ResponseCompression.ShouldGzip("gzip", ResponseCompression.MinBytes));
        Assert.True(ResponseCompression.ShouldGzip("gzip", ResponseCompression.MinBytes + 1));
        Assert.False(ResponseCompression.ShouldGzip(null, ResponseCompression.MinBytes * 4));
    }

    [Fact]
    public void Gzip_round_trips()
    {
        var body = Encoding.UTF8.GetBytes("{\"elements\": [" + string.Join(",", Enumerable.Repeat("{\"id\": 1}", 20000)) + "]}");
        var packed = ResponseCompression.Gzip(body);
        Assert.True(packed.Length < body.Length);
        using var input = new GZipStream(new MemoryStream(packed), CompressionMode.Decompress);
        using var output = new MemoryStream();
        input.CopyTo(output);
        Assert.Equal(body, output.ToArray());
    }
}

public class UniqueIdCacheTests
{
    [Fact]
    public void Put_then_get_per_document()
    {
        var cache = new UniqueIdCache();
        cache.Put("doc-a", "uid-1", 11);
        Assert.True(cache.TryGet("doc-a", "uid-1", out var id));
        Assert.Equal(11, id);
        Assert.False(cache.TryGet("doc-b", "uid-1", out _));
    }

    [Fact]
    public void Deleted_element_ids_are_dropped()
    {
        var cache = new UniqueIdCache();
        cache.Put("doc", "uid-1", 11);
        cache.Put("doc", "uid-2", 12);
        cache.RemoveElementIds("doc", new long[] { 11, 999 });
        Assert.False(cache.TryGet("doc", "uid-1", out _));
        Assert.True(cache.TryGet("doc", "uid-2", out _));
    }

    [Fact]
    public void Closing_a_document_drops_only_that_document()
    {
        var cache = new UniqueIdCache();
        cache.Put("doc-a", "uid-1", 11);
        cache.Put("doc-b", "uid-2", 12);
        cache.ClearDocument("doc-a");
        Assert.Equal(0, cache.Count("doc-a"));
        Assert.True(cache.TryGet("doc-b", "uid-2", out _));
    }

    [Fact]
    public void Switching_the_active_document_clears_the_cache()
    {
        var cache = new UniqueIdCache();
        cache.SetActiveDocument("doc-a");
        cache.Put("doc-a", "uid-1", 11);
        cache.SetActiveDocument("doc-a");
        Assert.True(cache.TryGet("doc-a", "uid-1", out _));
        cache.SetActiveDocument("doc-b");
        Assert.False(cache.TryGet("doc-a", "uid-1", out _));
    }

    [Fact]
    public void A_reused_element_id_replaces_the_old_unique_id()
    {
        var cache = new UniqueIdCache();
        cache.Put("doc", "uid-old", 11);
        cache.Put("doc", "uid-new", 11);
        Assert.False(cache.TryGet("doc", "uid-old", out _));
        cache.RemoveElementIds("doc", new long[] { 11 });
        Assert.False(cache.TryGet("doc", "uid-new", out _));
    }

    [Fact]
    public void The_cache_is_bounded_per_document()
    {
        var cache = new UniqueIdCache(maxEntriesPerDocument: 2);
        cache.Put("doc", "a", 1);
        cache.Put("doc", "b", 2);
        cache.Put("doc", "c", 3);
        Assert.Equal(1, cache.Count("doc"));
        Assert.True(cache.TryGet("doc", "c", out _));
    }

    [Fact]
    public void Forget_drops_one_entry()
    {
        var cache = new UniqueIdCache();
        cache.Put("doc", "uid-1", 11);
        cache.Forget("doc", "uid-1");
        Assert.False(cache.TryGet("doc", "uid-1", out _));
        cache.RemoveElementIds("doc", new long[] { 11 });
    }
}
