using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Text.Json;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevitBridge.Bridge;

public static partial class BridgeCommandFactory
{
    // Above zero while revit.execute_plan_batch runs its actions on this thread.
    [ThreadStatic]
    private static int _planBatchDepth;

    // ==================== PLAN BATCH (#294) ====================

    // Runs the write actions of one approved plan in this one ExternalEvent turn, inside one
    // TransactionGroup, so the whole plan is one undo step named
    // "AEC Model Bridge: <plan title> (<short id>)". Each action still runs through its own handler
    // from the dispatch table and opens its own transaction inside the group. The run stops at the
    // first failure, rolls the group back and reports every action: the failed one, the ones rolled
    // back with it and the ones not run. On success the group is assimilated into one undo step.
    // A TransactionGroup must start and end in the same API context, so there are no separate begin
    // and end commands. Only plain model writes (PlanBatch.IsBatchable) are accepted; the MCP server
    // sends anything else one action at a time. UNVERIFIED in live Revit.
    [BridgeCommand("revit.execute_plan_batch", IsMutating = true)]
    private static object ExecutePlanBatch(UIApplication app, JsonElement payload)
    {
        if (InReadBatch || _planBatchDepth > 0)
            throw new InvalidOperationException("revit.execute_plan_batch cannot run inside another batch.");

        var request = PlanBatch.Parse(payload, IsRegisteredCommand);

        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");
        if (doc.IsReadOnly)
            throw new InvalidOperationException("The active document is read-only, so the plan cannot run.");
        if (doc.IsModifiable)
            throw new InvalidOperationException("A transaction is already open in the active document, so the plan cannot start its undo group.");

        var groupName = PlanBatch.GroupName(request.Title, request.PlanId);
        var actions = request.Actions;
        var outcomes = new object?[actions.Count];
        var okResults = new object?[actions.Count];
        var failedIndex = -1;
        string? failureReason = null;
        var committed = false;
        var groupStatus = TransactionStatus.Uninitialized;
        var clock = Stopwatch.StartNew();

        _planBatchDepth++;
        TransactionGroup? group = null;
        try
        {
            group = new TransactionGroup(doc, groupName);
            groupStatus = group.Start();
            if (groupStatus != TransactionStatus.Started)
                throw new InvalidOperationException($"Revit did not start the undo group for the plan (status {groupStatus}). Nothing was changed.");

            for (var i = 0; i < actions.Count; i++)
            {
                var action = actions[i];
                if (clock.ElapsedMilliseconds > PlanBatch.TimeBudgetMs)
                {
                    failedIndex = i;
                    failureReason = $"Not run: the plan passed its {PlanBatch.TimeBudgetMs / 1000} s budget.";
                    outcomes[i] = new { index = action.Index, action_id = action.ActionId, tool = action.Tool, ok = false, not_run = true, error = failureReason };
                    break;
                }

                try
                {
                    var result = Execute(app, action.Tool, action.Payload);
                    string? json = null;
                    try { json = JsonSerializer.Serialize(result); }
                    catch (Exception) { json = null; }
                    if (PlanBatch.IsExplicitFailure(json))
                    {
                        failedIndex = i;
                        failureReason = PlanBatch.FailureText(json);
                        outcomes[i] = new { index = action.Index, action_id = action.ActionId, tool = action.Tool, ok = false, error = failureReason, result };
                        break;
                    }
                    okResults[i] = result;
                }
                catch (Exception ex)
                {
                    var inner = ex is System.Reflection.TargetInvocationException tie && tie.InnerException != null ? tie.InnerException : ex;
                    failedIndex = i;
                    failureReason = inner.Message;
                    outcomes[i] = new
                    {
                        index = action.Index,
                        action_id = action.ActionId,
                        tool = action.Tool,
                        ok = false,
                        error = failureReason,
                        result = BridgeTransactionException.Find(inner)?.ToResult()
                    };
                    break;
                }
            }

            if (failedIndex < 0)
            {
                groupStatus = group.Assimilate();
                committed = groupStatus == TransactionStatus.Committed;
            }
            else
            {
                groupStatus = SafeRollBack(group);
            }
        }
        finally
        {
            if (group != null)
            {
                if (group.IsValidObject && group.GetStatus() == TransactionStatus.Started)
                    groupStatus = SafeRollBack(group);
                group.Dispose();
            }
            _planBatchDepth--;
        }

        var results = new List<object>(actions.Count);
        for (var i = 0; i < actions.Count; i++)
        {
            var action = actions[i];
            if (outcomes[i] != null)
            {
                results.Add(outcomes[i]!);
            }
            else if (committed)
            {
                results.Add(new { index = action.Index, action_id = action.ActionId, tool = action.Tool, ok = true, result = okResults[i] });
            }
            else if (failedIndex < 0)
            {
                // Every action ran but Revit did not keep the group as one undo step.
                results.Add(new
                {
                    index = action.Index,
                    action_id = action.ActionId,
                    tool = action.Tool,
                    ok = false,
                    group_not_committed = true,
                    error = $"Revit did not keep the plan as one undo step (status {groupStatus}). Check the model before drafting a new plan."
                });
            }
            else if (i < failedIndex)
            {
                results.Add(new
                {
                    index = action.Index,
                    action_id = action.ActionId,
                    tool = action.Tool,
                    ok = false,
                    rolled_back = true,
                    error = $"Rolled back: action {failedIndex + 1} of the plan failed, so the whole plan was undone."
                });
            }
            else
            {
                results.Add(new
                {
                    index = action.Index,
                    action_id = action.ActionId,
                    tool = action.Tool,
                    ok = false,
                    not_run = true,
                    error = $"Not run: action {failedIndex + 1} of the plan failed first."
                });
            }
        }

        return new
        {
            plan_batch = true,
            plan_id = request.PlanId,
            group_name = groupName,
            committed,
            group_status = groupStatus.ToString(),
            failed_index = failedIndex,
            failure = failureReason,
            elapsed_ms = clock.ElapsedMilliseconds,
            count = results.Count,
            results
        };
    }

    private static TransactionStatus SafeRollBack(TransactionGroup group)
    {
        try
        {
            if (group.IsValidObject && group.GetStatus() == TransactionStatus.Started)
                return group.RollBack();
            return group.IsValidObject ? group.GetStatus() : TransactionStatus.Error;
        }
        catch (Exception)
        {
            return TransactionStatus.Error;
        }
    }

    /// <summary>True when the dispatch table has a handler for this command.</summary>
    internal static bool IsRegisteredCommand(string tool)
    {
        return !string.IsNullOrEmpty(tool) && _handlers.ContainsKey(tool);
    }
}
