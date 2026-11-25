using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Text.Json;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Events;
using Autodesk.Revit.UI;

namespace RevitBridge.Bridge;

public static partial class BridgeCommandFactory
{
    // ==================== PLAN PREVIEW (#293) ====================

    // Runs the write actions of a draft plan inside one TransactionGroup that is ALWAYS rolled back, and
    // reports what they would have done: each action's outcome (with the Revit warnings its transaction
    // raised), and the element ids Revit says were added, modified or deleted. Nothing is kept: the group is
    // rolled back on success, on a failed action and on an exception. The result says rolled_back and, if
    // Revit did not confirm the rollback, rolled_back false so the server can tell the person to check the
    // model. This is not an execution and not an approval: the MCP server claims nothing and records
    // nothing, and the request is the same shape as revit.execute_plan_batch, with the same allowlist
    // (PlanBatch.IsBatchable). A TransactionGroup must start and end in the same API context, so there is
    // one command. UNVERIFIED in live Revit.
    [BridgeCommand("revit.preview_plan_batch", IsMutating = true)]
    private static object PreviewPlanBatch(UIApplication app, JsonElement payload)
    {
        if (InReadBatch || _planBatchDepth > 0)
            throw new InvalidOperationException("revit.preview_plan_batch cannot run inside another batch.");

        var request = PlanBatch.Parse(payload, IsRegisteredCommand, "revit.preview_plan_batch");

        var doc = app.ActiveUIDocument?.Document;
        if (doc == null)
            throw new InvalidOperationException("No active document");
        if (doc.IsReadOnly)
            throw new InvalidOperationException("The active document is read-only, so the plan cannot be previewed.");
        if (doc.IsModifiable)
            throw new InvalidOperationException("A transaction is already open in the active document, so the preview cannot start.");

        var actions = request.Actions;
        var outcomes = new List<object>(actions.Count);
        var added = new HashSet<long>();
        var modified = new HashSet<long>();
        var deleted = new HashSet<long>();
        var collecting = false;
        var failedIndex = -1;
        string? failureReason = null;
        var groupStatus = TransactionStatus.Uninitialized;
        var rolledBack = false;
        var clock = Stopwatch.StartNew();

        EventHandler<DocumentChangedEventArgs> onChanged = (sender, args) =>
        {
            if (!collecting) return;
            var changed = args.GetDocument();
            if (changed == null || !changed.Equals(doc)) return;
            foreach (var id in args.GetAddedElementIds()) added.Add(id.Value);
            foreach (var id in args.GetModifiedElementIds()) modified.Add(id.Value);
            foreach (var id in args.GetDeletedElementIds()) deleted.Add(id.Value);
        };

        _planBatchDepth++;
        TransactionGroup? group = null;
        var subscribed = false;
        try
        {
            app.Application.DocumentChanged += onChanged;
            subscribed = true;
            group = new TransactionGroup(doc, "AEC Model Bridge: preview (rolled back)");
            groupStatus = group.Start();
            if (groupStatus != TransactionStatus.Started)
                throw new InvalidOperationException($"Revit did not start the preview group (status {groupStatus}). Nothing was changed.");
            collecting = true;

            for (var i = 0; i < actions.Count; i++)
            {
                var action = actions[i];
                if (failedIndex >= 0)
                {
                    outcomes.Add(new { index = action.Index, action_id = action.ActionId, tool = action.Tool, ok = false, not_run = true, error = $"Not run: action {failedIndex + 1} failed first." });
                    continue;
                }
                if (clock.ElapsedMilliseconds > PlanBatch.TimeBudgetMs)
                {
                    failedIndex = i;
                    failureReason = $"Not run: the preview passed its {PlanBatch.TimeBudgetMs / 1000} s budget.";
                    outcomes.Add(new { index = action.Index, action_id = action.ActionId, tool = action.Tool, ok = false, not_run = true, error = failureReason });
                    continue;
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
                        outcomes.Add(new { index = action.Index, action_id = action.ActionId, tool = action.Tool, ok = false, error = failureReason, result });
                    }
                    else
                    {
                        outcomes.Add(new { index = action.Index, action_id = action.ActionId, tool = action.Tool, ok = true, result });
                    }
                }
                catch (Exception ex)
                {
                    var inner = ex is System.Reflection.TargetInvocationException tie && tie.InnerException != null ? tie.InnerException : ex;
                    failedIndex = i;
                    failureReason = inner.Message;
                    outcomes.Add(new
                    {
                        index = action.Index,
                        action_id = action.ActionId,
                        tool = action.Tool,
                        ok = false,
                        error = failureReason,
                        result = BridgeTransactionException.Find(inner)?.ToResult()
                    });
                }
            }

            // Stop collecting before the rollback, so undoing the changes is not reported as changes.
            collecting = false;
            groupStatus = SafeRollBack(group);
            rolledBack = groupStatus == TransactionStatus.RolledBack;
        }
        finally
        {
            collecting = false;
            if (group != null)
            {
                // An exception before the rollback above still ends in a rollback, never a commit.
                if (group.IsValidObject && group.GetStatus() == TransactionStatus.Started)
                {
                    groupStatus = SafeRollBack(group);
                    rolledBack = groupStatus == TransactionStatus.RolledBack;
                }
                group.Dispose();
            }
            if (subscribed)
            {
                try { app.Application.DocumentChanged -= onChanged; }
                catch (Exception) { /* nothing to undo if Revit already dropped the handler */ }
            }
            _planBatchDepth--;
        }

        return new
        {
            plan_preview = true,
            committed = false,
            rolled_back = rolledBack,
            group_status = groupStatus.ToString(),
            failed_index = failedIndex,
            failure = failureReason,
            elapsed_ms = clock.ElapsedMilliseconds,
            changed_element_ids = new
            {
                added = added.OrderBy(id => id).ToList(),
                modified = modified.OrderBy(id => id).ToList(),
                deleted = deleted.OrderBy(id => id).ToList()
            },
            count = outcomes.Count,
            results = outcomes
        };
    }
}
