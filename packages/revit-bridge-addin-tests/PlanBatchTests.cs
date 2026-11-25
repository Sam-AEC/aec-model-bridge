using System;
using System.Collections.Generic;
using System.Linq;
using RevitBridge.Bridge;
using Xunit;

namespace RevitBridge.Tests;

public class PlanBatchTests
{
    private static readonly HashSet<string> Registered = new() { "revit.set_parameter_value", "revit.move_element", "revit.rotate_element", "revit.create_wall" };

    private static PlanBatchRequest Parse(string json) => PlanBatch.Parse(Json.Parse(json), Registered.Contains);

    private const string OneAction = "{\"action_id\": \"act_1\", \"tool\": \"revit.set_parameter_value\", \"payload\": {\"element_id\": 1, \"parameter_name\": \"Mark\", \"value\": \"A\"}}";

    [Fact]
    public void Actions_are_returned_in_order_with_their_ids_and_payloads()
    {
        var request = Parse("{\"plan_id\": \"plan_abcdef123456\", \"title\": \"Set marks\", \"actions\": [" + OneAction
            + ", {\"action_id\": \"act_2\", \"tool\": \"revit.move_element\", \"payload\": {\"element_id\": 2}}]}");
        Assert.Equal("plan_abcdef123456", request.PlanId);
        Assert.Equal("Set marks", request.Title);
        Assert.Equal(new[] { "act_1", "act_2" }, request.Actions.Select(a => a.ActionId));
        Assert.Equal(new[] { 0, 1 }, request.Actions.Select(a => a.Index));
        Assert.Equal(2, request.Actions[1].Payload.GetProperty("element_id").GetInt32());
    }

    [Theory]
    [InlineData("revit.create_wall")]
    [InlineData("revit.execute_python")]
    [InlineData("revit.export_image")]
    [InlineData("revit.execute_plan_batch")]
    [InlineData("revit.preview_plan_batch")]
    [InlineData("revit.batch")]
    public void A_member_that_is_not_a_plain_model_write_refuses_the_whole_request(string tool)
    {
        var ex = Assert.Throws<ArgumentException>(() => Parse("{\"plan_id\": \"plan_1\", \"actions\": [" + OneAction
            + ", {\"action_id\": \"act_2\", \"tool\": \"" + tool + "\", \"payload\": {}}]}"));
        Assert.Contains(tool, ex.Message);
        Assert.False(PlanBatch.IsBatchable(tool));
    }

    [Fact]
    public void The_preview_command_takes_the_same_request_and_names_itself_in_errors()
    {
        var json = "{\"plan_id\": \"preview\", \"actions\": [" + OneAction + "]}";
        Assert.Single(PlanBatch.Parse(Json.Parse(json), Registered.Contains, "revit.preview_plan_batch").Actions);
        var ex = Assert.Throws<ArgumentException>(() =>
            PlanBatch.Parse(Json.Parse("{\"plan_id\": \"preview\", \"actions\": []}"), Registered.Contains, "revit.preview_plan_batch"));
        Assert.StartsWith("revit.preview_plan_batch ", ex.Message);
        var wall = "{\"action_id\": \"act_2\", \"tool\": \"revit.create_wall\", \"payload\": {}}";
        Assert.Throws<ArgumentException>(() =>
            PlanBatch.Parse(Json.Parse("{\"plan_id\": \"preview\", \"actions\": [" + wall + "]}"), Registered.Contains, "revit.preview_plan_batch"));
    }

    [Fact]
    public void An_unregistered_command_is_refused()
    {
        var ex = Assert.Throws<ArgumentException>(() =>
            PlanBatch.Parse(Json.Parse("{\"plan_id\": \"plan_1\", \"actions\": [" + OneAction + "]}"), _ => false));
        Assert.Contains("not a command this add-in has", ex.Message);
    }

    [Fact]
    public void The_action_count_is_capped()
    {
        var items = string.Join(",", Enumerable.Range(0, PlanBatch.MaxActions + 1).Select(i =>
            "{\"action_id\": \"act_" + i + "\", \"tool\": \"revit.move_element\", \"payload\": {}}"));
        var ex = Assert.Throws<ArgumentException>(() => Parse("{\"plan_id\": \"plan_1\", \"actions\": [" + items + "]}"));
        Assert.Contains("at most " + PlanBatch.MaxActions, ex.Message);
    }

    [Theory]
    [InlineData("[]")]
    [InlineData("{\"actions\": []}")]
    [InlineData("{\"plan_id\": \"plan 1\", \"actions\": []}")]
    [InlineData("{\"plan_id\": \"plan_1\"}")]
    [InlineData("{\"plan_id\": \"plan_1\", \"actions\": []}")]
    [InlineData("{\"plan_id\": \"plan_1\", \"title\": 5, \"actions\": [{\"action_id\": \"a\", \"tool\": \"revit.move_element\", \"payload\": {}}]}")]
    [InlineData("{\"plan_id\": \"plan_1\", \"actions\": [{\"tool\": \"revit.move_element\", \"payload\": {}}]}")]
    [InlineData("{\"plan_id\": \"plan_1\", \"actions\": [{\"action_id\": \"a\", \"payload\": {}}]}")]
    [InlineData("{\"plan_id\": \"plan_1\", \"actions\": [{\"action_id\": \"a\", \"tool\": \"revit.move_element\"}]}")]
    [InlineData("{\"plan_id\": \"plan_1\", \"actions\": [{\"action_id\": \"a\", \"tool\": \"revit.move_element\", \"payload\": {}}, {\"action_id\": \"a\", \"tool\": \"revit.move_element\", \"payload\": {}}]}")]
    public void Malformed_requests_are_refused(string json)
    {
        Assert.Throws<ArgumentException>(() => Parse(json));
    }

    [Fact]
    public void The_group_name_carries_the_title_and_a_short_plan_id()
    {
        Assert.Equal("AEC Model Bridge: Set marks (abcdef12)", PlanBatch.GroupName("Set marks", "plan_abcdef123456"));
        Assert.Equal("AEC Model Bridge: plan (abcdef12)", PlanBatch.GroupName("  ", "plan_abcdef123456"));
        Assert.Equal("AEC Model Bridge: a b (x)", PlanBatch.GroupName("a\r\n\tb", "x"));
        var longName = PlanBatch.GroupName(new string('w', 200), "plan_1");
        Assert.True(longName.Length < 120);
        Assert.EndsWith("... (1)", longName);
    }

    [Theory]
    [InlineData("{\"status\": \"error\", \"message\": \"no\"}", true)]
    [InlineData("{\"success\": false}", true)]
    [InlineData("{\"ok\": false}", true)]
    [InlineData("{\"status\": \"failed\"}", true)]
    [InlineData("{\"status\": \"success\"}", false)]
    [InlineData("{\"element_id\": 5}", false)]
    [InlineData("[1]", false)]
    [InlineData("not json", false)]
    [InlineData(null, false)]
    public void Explicit_failures_are_recognised_like_the_server_does(string? json, bool failed)
    {
        Assert.Equal(failed, PlanBatch.IsExplicitFailure(json));
    }

    [Fact]
    public void Failure_text_prefers_error_then_message()
    {
        Assert.Equal("bad", PlanBatch.FailureText("{\"error\": \"bad\", \"message\": \"m\"}"));
        Assert.Equal("m", PlanBatch.FailureText("{\"status\": \"error\", \"message\": \"m\"}"));
        Assert.Equal("inner", PlanBatch.FailureText("{\"error\": {\"message\": \"inner\"}}"));
        Assert.Equal("The command reported a failure.", PlanBatch.FailureText("{}"));
    }
}
