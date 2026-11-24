using System;
using System.Diagnostics;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Events;
using Serilog;

namespace RevitBridge.Bridge;

public class RevitCommandExecutor : IExternalEventHandler
{
    private readonly CommandQueue _queue;
    private readonly Func<string, bool> _isReadOnly;
    private readonly int _turnBudgetMs;
    private readonly FastWakeGate _wake;
    private UIApplication? _wakeApp;

    /// <summary>Set by App after the event is created, so the executor can ask Revit for another turn.</summary>
    public ExternalEvent? Event { get; set; }

    public RevitCommandExecutor(CommandQueue queue)
        : this(queue, BridgeCommandFactory.IsReadOnlyCommand, ExecutorTurnPolicy.ReadBudgetMs(), ExecutorTurnPolicy.ReadFastWake())
    {
    }

    internal RevitCommandExecutor(CommandQueue queue, Func<string, bool> isReadOnly, int turnBudgetMs, bool fastWake)
    {
        _queue = queue;
        _isReadOnly = isReadOnly;
        _turnBudgetMs = turnBudgetMs;
        _wake = new FastWakeGate(fastWake);
    }

    public void Execute(UIApplication app)
    {
        // A turn always starts with one request. Looping over the whole queue inside a single Execute kept
        // Revit's UI thread busy until every queued request finished (the 2026-10-13 freeze), so further
        // requests join the turn only while (a) every request so far may share a turn, (b) the next one may
        // too, and (c) the turn is still under its budget (AEC_BRIDGE_TURN_BUDGET_MS, default 40 ms; 0 runs
        // one request per turn). Only read-only commands may share a turn (ExecutorTurnPolicy.MayShareTurn).
        // A write or unknown command runs alone: nothing is added before or after it in the same turn.
        // Revit processes its own messages between turns, and we ask for another turn if more are waiting.
        var turn = Stopwatch.StartNew();
        var ran = 0;
        var lastShared = true;
        try
        {
            while (ExecutorTurnPolicy.MayTakeAnother(ran, lastShared, turn.ElapsedMilliseconds, _turnBudgetMs))
            {
                CommandRequest? request;
                var taken = ran == 0
                    ? _queue.TryDequeue(out request)
                    : _queue.TryDequeueIf(next => MayShareTurn(next), out request);
                if (!taken) break;
                if (request == null) continue;

                if (!_queue.IsWanted(request.RequestId))
                {
                    Log.Information("Skipping {Tool} request {RequestId}: nobody asked about it for {Seconds}s", request.Tool, request.RequestId, _queue.AbandonAfter.TotalSeconds);
                    _queue.Complete(request.RequestId, new CommandResponse { Status = "error", Tool = request.Tool, Message = "Abandoned before it started" });
                    continue;
                }

                lastShared = MayShareTurn(request);
                RunOne(app, request);
                ran++;
            }
        }
        finally
        {
            if (ran > 1)
            {
                Log.Information("Ran {Count} read-only requests in one turn in {ElapsedMs}ms", ran, turn.ElapsedMilliseconds);
            }
            var remaining = _queue.Count;
            if (remaining > 0)
            {
                try { Event?.Raise(); } catch (Exception ex) { Log.Warning(ex, "Could not re-raise the command executor"); }
            }
            UpdateFastWake(app, remaining);
        }
    }

    private bool MayShareTurn(CommandRequest request)
    {
        return ExecutorTurnPolicy.MayShareTurn(request.Tool, _isReadOnly);
    }

    // Optional prompt wake (#288), off unless AEC_BRIDGE_FAST_WAKE=1. Revit runs a raised ExternalEvent at its
    // next idle cycle, and some machines report that cycle waiting until the mouse moves. While requests are
    // still queued after a turn, an Idling handler calls SetRaiseWithoutDelay so Revit keeps cycling and picks
    // up the next turn at once. CPU trade-off: SetRaiseWithoutDelay keeps Revit's UI thread busy (one core) for
    // as long as the handler is attached (Autodesk documents this), so the handler is attached only while the
    // queue is non-empty and removed as soon as it is empty; idle CPU use stays at zero. Revit events can only
    // be attached on the Revit thread, so it is attached at the end of a turn: the first request after an idle
    // period still waits for Revit's normal ExternalEvent pickup.
    private void UpdateFastWake(UIApplication app, int queued)
    {
        if (_wake.ShouldAttach(queued))
        {
            try
            {
                app.Idling += OnIdling;
                _wakeApp = app;
            }
            catch (Exception ex)
            {
                _wake.MarkDetached();
                Log.Warning(ex, "Could not attach the fast-wake Idling handler");
            }
        }
        else if (_wake.ShouldDetach(queued))
        {
            DetachFastWake(app);
        }
    }

    private void OnIdling(object? sender, IdlingEventArgs e)
    {
        if (_queue.Count > 0)
        {
            e.SetRaiseWithoutDelay();
            try { Event?.Raise(); } catch (Exception ex) { Log.Warning(ex, "Could not raise the command executor from Idling"); }
            return;
        }
        if (_wake.ShouldDetach(0))
        {
            DetachFastWake(sender as UIApplication ?? _wakeApp);
        }
    }

    private void DetachFastWake(UIApplication? app)
    {
        try
        {
            if (app != null) app.Idling -= OnIdling;
        }
        catch (Exception ex)
        {
            Log.Warning(ex, "Could not detach the fast-wake Idling handler");
        }
        _wakeApp = null;
    }

    private void RunOne(UIApplication app, CommandRequest request)
    {
        try
        {
            Log.Information("Executing {Tool} request {RequestId}", request.Tool, request.RequestId);
            _queue.MarkRunning(request.RequestId);

            var result = BridgeCommandFactory.Execute(app, request.Tool, request.Payload);

            _queue.Complete(request.RequestId, new CommandResponse
            {
                Status = "ok",
                Tool = request.Tool,
                Result = result
            });
            Log.Information("Completed {Tool} request {RequestId}", request.Tool, request.RequestId);
        }
        catch (Exception ex)
        {
            Log.Error(ex, "Error executing {Tool} request {RequestId}", request.Tool, request.RequestId);
            // Reflection commands may wrap the checked-commit exception. Keep its
            // structured failure in the durable error envelope instead of dropping IDs.
            var transactionFailure = BridgeTransactionException.Find(ex);

            _queue.Complete(request.RequestId, new CommandResponse
            {
                Status = "error",
                Tool = request.Tool,
                Result = transactionFailure?.ToResult(),
                Message = ex.Message,
                StackTrace = ex.StackTrace
            });
        }
    }

    public string GetName() => "AEC Model Bridge Command Executor";
}
