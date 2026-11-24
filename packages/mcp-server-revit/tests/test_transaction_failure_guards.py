"""Compile production transaction handling against controlled Revit API doubles.

These prove bridge policy and envelopes; Revit's own failure-posting behaviour
still needs acceptance in a scratch model with the rebuilt DLL loaded.
"""
from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[3]
BRIDGE = ROOT / "packages/revit-bridge-addin/src/Bridge"


def test_factory_has_no_unchecked_or_raw_transactions():
    source = (BRIDGE / "BridgeCommandFactory.cs").read_text(encoding="utf-8")
    assert not re.search(r"\b(?:trans|tx)\.Commit\(", source)
    assert "new Transaction(" not in source
    assert source.count(".CommitChecked();") >= 59  # place_door/place_window share one commit in PlaceHostedOpening
    assert "BridgeTransactionResults.AppendWarnings(result, _currentTransactionMessages)" in source
    # Cleared after each command: Execute restores the value it found (null at the top level, the
    # batch's own list for a revit.batch member).
    assert "var outerMessages = _currentTransactionMessages;" in source
    assert "_currentTransactionMessages = outerMessages;" in source


STUBS = r"""
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using Autodesk.Revit.DB;
using RevitBridge.Bridge;

namespace Autodesk.Revit.DB
{
    public enum TransactionStatus { Uninitialized, Started, Committed, RolledBack, Pending, Error }
    public enum FailureSeverity { None, Warning, Error, DocumentCorruption }
    public enum FailureProcessingResult { Continue, ProceedWithRollBack }
    public interface IFailuresPreprocessor { FailureProcessingResult PreprocessFailures(FailuresAccessor accessor); }
    public class ElementId { public long Value; public ElementId(long value) { Value = value; } }
    public class FailureDefinitionId { public Guid Guid = Guid.NewGuid(); }
    public class FailureMessageAccessor
    {
        public FailureSeverity Severity;
        public string Text = "";
        public long[] Ids = Array.Empty<long>(), Additional = Array.Empty<long>();
        private readonly FailureDefinitionId _id = new();
        public FailureSeverity GetSeverity() => Severity;
        public string GetDescriptionText() => Text;
        public FailureDefinitionId GetFailureDefinitionId() => _id;
        public ICollection<ElementId> GetFailingElementIds() => Ids.Select(id => new ElementId(id)).ToList();
        public ICollection<ElementId> GetAdditionalElementIds() => Additional.Select(id => new ElementId(id)).ToList();
    }
    public class FailuresAccessor
    {
        public List<FailureMessageAccessor> Messages = new();
        public int Deleted;
        public IList<FailureMessageAccessor> GetFailureMessages() => Messages;
        public void DeleteWarning(FailureMessageAccessor message)
        {
            if (message.Severity != FailureSeverity.Warning) throw new Exception("Deleted an error");
            Deleted++;
        }
    }
    public class FailureHandlingOptions : IDisposable
    {
        public IFailuresPreprocessor? Processor;
        public bool Clear, Modal;
        public void SetFailuresPreprocessor(IFailuresPreprocessor processor) { Processor = processor; }
        public void SetClearAfterRollback(bool clear) { Clear = clear; }
        public void SetForcedModalHandling(bool modal) { Modal = modal; }
        public void Dispose() { }
    }
    public class Document
    {
        public TransactionStatus StartStatus = TransactionStatus.Started;
        public TransactionStatus CommitStatus = TransactionStatus.Committed;
        public TransactionStatus? FinalStatus;
        public bool ThrowOnCommit;
        public FailuresAccessor Failures = new();
        public Transaction? Last;
    }
    public class Transaction : IDisposable
    {
        private readonly Document _doc;
        private TransactionStatus _status;
        public FailureHandlingOptions Options = new();
        public int Rollbacks;
        public bool Disposed;
        public Transaction(Document doc, string name) { _doc = doc; doc.Last = this; }
        public TransactionStatus Start()
        {
            Options = new(); // Matches Revit's reset at every Start.
            return _status = _doc.StartStatus;
        }
        public FailureHandlingOptions GetFailureHandlingOptions() => Options;
        public void SetFailureHandlingOptions(FailureHandlingOptions options) { Options = options; }
        public TransactionStatus GetStatus() => _status;
        public TransactionStatus Commit()
        {
            if (_doc.ThrowOnCommit) throw new InvalidOperationException("API commit threw");
            if (_doc.Failures.Messages.Count > 0)
            {
                var outcome = Options.Processor!.PreprocessFailures(_doc.Failures);
                if (outcome == FailureProcessingResult.ProceedWithRollBack)
                {
                    if (!Options.Clear) throw new Exception("Would show rollback dialog");
                    return RollBack();
                }
            }
            _status = _doc.FinalStatus ?? _doc.CommitStatus;
            return _doc.CommitStatus;
        }
        public TransactionStatus RollBack()
        {
            if (_status != TransactionStatus.Started) throw new Exception("Invalid rollback state");
            Rollbacks++;
            return _status = TransactionStatus.RolledBack;
        }
        public void Dispose() { Disposed = true; }
    }
}

namespace Autodesk.Revit.UI
{
    public class UIApplication
    {
        public event EventHandler<Autodesk.Revit.UI.Events.IdlingEventArgs>? Idling;
        public int IdlingHandlers => Idling?.GetInvocationList().Length ?? 0;
    }
    public interface IExternalEventHandler { void Execute(UIApplication app); string GetName(); }
    public class ExternalEvent { public void Raise() { } }
}
namespace Autodesk.Revit.UI.Events
{
    public class IdlingEventArgs : EventArgs { public void SetRaiseWithoutDelay() { } }
}
namespace Serilog
{
    public static class Log
    {
        public static void Information(string message, params object[] values) { }
        public static void Warning(Exception e, string message, params object[] values) { }
        public static void Error(Exception e, string message, params object[] values) { }
    }
}
namespace RevitBridge.Bridge
{
    public class CommandRequest
    {
        public string RequestId = "id", Tool = "test";
        public JsonElement Payload;
    }
    public class CommandResponse
    {
        public string Status = "ok", Tool = "";
        public object? Result;
        public string? Message, StackTrace;
    }
    public class CommandQueue
    {
        public int Count;
        // When set, the tools handed out in order (Count follows it).
        public Queue<string>? Pending;
        public TimeSpan AbandonAfter = TimeSpan.FromMinutes(1);
        public string State = "queued";
        public CommandResponse? Response;
        public bool TryDequeue(out CommandRequest? request)
        {
            if (Pending != null)
            {
                request = Pending.Count > 0 ? new CommandRequest { Tool = Pending.Dequeue() } : null;
                Count = Pending.Count;
                return request != null;
            }
            request = Count-- > 0 ? new CommandRequest() : null;
            return request != null;
        }
        public bool TryDequeueIf(Func<CommandRequest, bool> accept, out CommandRequest? request)
        {
            request = null;
            if (Pending == null || Pending.Count == 0 || !accept(new CommandRequest { Tool = Pending.Peek() })) return false;
            return TryDequeue(out request);
        }
        public bool IsWanted(string id) => true;
        public void MarkRunning(string id) { State = "running"; }
        public void Complete(string id, CommandResponse response)
        {
            Response = response;
            State = response.Status == "ok" ? "done" : "failed";
        }
    }
    public static class BridgeCommandFactory
    {
        public static Exception? Error;
        public static List<string> Calls = new List<string>();
        public static bool IsReadOnlyCommand(string tool) => false;
        public static object Execute(Autodesk.Revit.UI.UIApplication app, string tool, JsonElement payload)
        {
            Calls.Add(tool);
            if (Error != null) throw Error;
            return new { element_id = 123 };
        }
    }
}

public class Program
{
    static void Check(bool condition, string message)
    {
        if (!condition) throw new Exception(message);
    }
    static BridgeTransactionException Failed(BridgeTransaction tx)
    {
        try { tx.CommitChecked(); }
        catch (BridgeTransactionException failure) { return failure; }
        throw new Exception("Returned success for failed commit");
    }
    static JsonElement Json(object value) => JsonSerializer.SerializeToElement(value,
        new JsonSerializerOptions { IncludeFields = true });

    static int Turns()
    {
        // #287: reads share a turn, a write runs alone, budget 0 means one request per turn.
        var app = new Autodesk.Revit.UI.UIApplication();
        var turns = new CommandQueue { Pending = new Queue<string>(new[] { "read", "read", "write", "read" }), Count = 4 };
        var executor = new RevitCommandExecutor(turns, t => t == "read", 200, false);
        executor.Execute(app);
        Check(BridgeCommandFactory.Calls.SequenceEqual(new[] { "read", "read" }), "reads did not share a turn, or the write joined them");
        executor.Execute(app);
        Check(BridgeCommandFactory.Calls.Count == 3 && BridgeCommandFactory.Calls[2] == "write", "the write did not run alone");
        executor.Execute(app);
        Check(BridgeCommandFactory.Calls.Count == 4 && turns.Count == 0, "the last read did not run");
        var single = new CommandQueue { Pending = new Queue<string>(new[] { "read", "read" }), Count = 2 };
        new RevitCommandExecutor(single, t => true, 0, false).Execute(app);
        Check(BridgeCommandFactory.Calls.Count == 5 && single.Count == 1, "budget 0 must run one request per turn");
        // #288: the Idling handler is attached only while work is queued, and only when enabled.
        var woken = new CommandQueue { Pending = new Queue<string>(new[] { "write", "write" }), Count = 2 };
        var waker = new RevitCommandExecutor(woken, t => false, 40, true);
        waker.Execute(app);
        Check(app.IdlingHandlers == 1, "fast wake not attached while work is queued");
        waker.Execute(app);
        Check(app.IdlingHandlers == 0, "fast wake still attached with an empty queue");
        var off = new CommandQueue { Pending = new Queue<string>(new[] { "write", "write" }), Count = 2 };
        new RevitCommandExecutor(off, t => false, 40, false).Execute(app);
        Check(app.IdlingHandlers == 0, "fast wake attached although it is off");
        Console.WriteLine("PASS turns");
        return 0;
    }

    public static int Main(string[] args)
    {
        if (args[0] == "turns") return Turns();
        var doc = new Document();
        var reported = new List<BridgeFailureMessage>();
        using var tx = new BridgeTransaction(doc, "test", messages => reported.AddRange(messages));
        string scenario = args[0];
        if (scenario == "start")
        {
            doc.StartStatus = TransactionStatus.Error;
            try { tx.Start(); throw new Exception("Start accepted Error"); }
            catch (BridgeTransactionException error) { Check(error.Kind == "transaction_not_started", "start kind"); }
            return 0;
        }
        tx.Start();
        Check(doc.Last!.Options.Clear && doc.Last.Options.Modal && doc.Last.Options.Processor != null,
            "failure options were not installed after Start");
        var warning = new FailureMessageAccessor { Severity = FailureSeverity.Warning, Text = "Off axis", Ids = new long[] { 3 } };
        switch (scenario)
        {
            case "warning":
                doc.Failures.Messages.AddRange(new[] { warning, warning });
                tx.CommitChecked();
                Check(doc.Last.GetStatus() == TransactionStatus.Committed && doc.Failures.Deleted == 2, "warnings blocked commit");
                Check(reported.Count == 1 && reported[0].Message == "Off axis", "warning lost or duplicated");
                var result = Json(BridgeTransactionResults.AppendWarnings(new { element_id = 123, warnings = new[] { "existing" } }, reported));
                Check(result.GetProperty("element_id").GetInt32() == 123, "command fields lost");
                Check(result.GetProperty("warnings").GetArrayLength() == 2, "existing warning lost");
                Check(result.GetProperty("revit_messages")[0].GetProperty("element_ids")[0].GetInt64() == 3, "warning IDs lost");
                break;
            case "error":
                doc.Failures.Messages.AddRange(new[] { warning, new FailureMessageAccessor
                    { Severity = FailureSeverity.Error, Text = "Window cannot cut host", Ids = new long[] { 11 }, Additional = new long[] { 12 } } });
                var failure = Failed(tx);
                Check(failure.Kind == "rolled_back" && doc.Last.Rollbacks == 1 && doc.Failures.Deleted == 1, "error not rolled back");
                Check(failure.FailedElementIds.SequenceEqual(new long[] { 11, 12 }), "failed IDs lost");
                var errorJson = Json(failure.ToResult());
                Check(!errorJson.GetProperty("ok").GetBoolean() && errorJson.GetProperty("rolled_back").GetBoolean(), "dishonest result");
                Check(errorJson.GetProperty("revit_messages").GetArrayLength() == 2, "Revit messages lost");
                Check(reported.Count == 0 && failure.Message.Contains("Window cannot cut host") && failure.Message.Contains("12"), "failure claimed success");
                break;
            case "rollback":
                doc.CommitStatus = TransactionStatus.RolledBack;
                Check(Failed(tx).Kind == "rolled_back", "silent rollback accepted");
                break;
            case "mismatch":
                doc.FinalStatus = TransactionStatus.RolledBack;
                Check(Failed(tx).Kind == "rolled_back", "ignored final status");
                break;
            case "exception":
                doc.ThrowOnCommit = true;
                var thrown = Failed(tx);
                Check(doc.Last.Rollbacks == 1 && thrown.InnerException!.Message == "API commit threw", "throw did not clean up");
                break;
            case "dispose":
                tx.Dispose();
                Check(doc.Last.Rollbacks == 1 && doc.Last.Disposed, "started transaction stranded");
                break;
            case "pending":
                doc.CommitStatus = TransactionStatus.Pending;
                var pending = Failed(tx);
                tx.Dispose();
                Check(pending.Kind == "revit_dialog_blocked" && !Json(pending.ToResult()).GetProperty("rolled_back").GetBoolean(), "Pending reported rollback");
                Check(doc.Last.Rollbacks == 0 && !doc.Last.Disposed, "attempted invalid Pending rollback/dispose");
                break;
            case "envelope":
                var structured = new BridgeTransactionException("test", TransactionStatus.RolledBack, "rolled_back",
                    new[] { new BridgeFailureMessage { Severity = "Error", Message = "Failed", ElementIds = new List<long> { 55 } } });
                BridgeCommandFactory.Error = new Exception("reflection wrapper", structured);
                var queue = new CommandQueue { Count = 1 };
                new RevitCommandExecutor(queue).Execute(new Autodesk.Revit.UI.UIApplication());
                Check(queue.State == "failed", "durable queue marked failure done");
                var envelope = Json(queue.Response!);
                Check(envelope.GetProperty("Status").GetString() == "error", "outer status is success");
                Check(envelope.GetProperty("Result").GetProperty("failed_element_ids")[0].GetInt64() == 55, "structured error dropped");
                break;
            default: throw new Exception("Unknown scenario");
        }
        Console.WriteLine("PASS " + scenario);
        return 0;
    }
}
"""


@pytest.fixture(scope="module")
def transaction_harness(tmp_path_factory):
    if shutil.which("dotnet") is None:
        pytest.skip("dotnet SDK is required for compiled transaction policy tests")
    directory = tmp_path_factory.mktemp("transaction-policy")
    (directory / "Policy.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        '<OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework>'
        '<Nullable>enable</Nullable></PropertyGroup></Project>', encoding="utf-8"
    )
    (directory / "Harness.cs").write_text(STUBS, encoding="utf-8")
    for name in ("BridgeTransaction.cs", "BridgeFailureText.cs", "ExternalEventHandler.cs", "ExecutorTurnPolicy.cs"):
        shutil.copyfile(BRIDGE / name, directory / name)
    built = subprocess.run(
        ["dotnet", "build", str(directory / "Policy.csproj"), "-c", "Release", "--nologo", "-v:q"],
        capture_output=True, text=True, timeout=120,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    return directory / "bin/Release/net8.0/Policy.dll"


@pytest.mark.parametrize("scenario", [
    "warning", "error", "rollback", "mismatch", "exception", "dispose", "pending", "start", "envelope", "turns",
])
def test_transaction_policy_behavior(transaction_harness, scenario):
    result = subprocess.run(
        ["dotnet", str(transaction_harness), scenario], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
