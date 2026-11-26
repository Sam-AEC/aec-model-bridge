using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Events;
using Autodesk.Revit.UI;
using Microsoft.Scripting.Hosting;

namespace RevitBridge.Bridge;

/// <summary>
/// Runs the script behind revit.execute_python on an engine from <see cref="PythonEngineFactory"/>
/// (which has no Revit dependency, so scripts/test-ironpython-runtime.ps1 can compile it alone).
/// Read mode is a safety rail against mistakes, not a security boundary: a text check refuses scripts
/// that name Transaction, SubTransaction or TransactionGroup, and a run-time backstop reports (and for
/// saves, cancels) anything that still touches the model.
/// </summary>
internal static class PythonScriptRunner
{
    internal const string ModeRead = "read";
    internal const string ModeWrite = "write";
    private const int MaxProgressLines = 200;
    private const int MaxProgressLineLength = 500;

    /// <summary>Progress lines of the script that is running now, for a future live status endpoint.</summary>
    internal static ProgressBuffer? ActiveProgress { get; private set; }

    internal static string NormalizeMode(string? value)
    {
        if (string.IsNullOrWhiteSpace(value)) return ModeWrite;
        var mode = value!.Trim().ToLowerInvariant();
        if (mode == ModeRead || mode == ModeWrite) return mode;
        throw new ArgumentException($"mode must be 'read' or 'write', got '{value}'");
    }

    internal static List<string> FindReadModeViolations(string script)
    {
        return ReadModeRules.FindViolations(script);
    }

    // ---- Warm engine (#286) ----
    // One engine per Revit session, with RevitAPI and RevitAPIUI loaded once. Each run gets a new ScriptScope
    // and its own output streams. Scripts run only on the Revit thread, one at a time, so these fields need no
    // lock. What a script leaves in shared Python state (sys.modules, builtins) is not reset between runs; the
    // engine is replaced after RecycleRuns scripts, when the document changes, when the per-run reset fails,
    // after an exception that may have broken the runtime, and after a script that touched the model in read
    // mode or left a transaction open.
    private static readonly int RecycleRuns = PythonEngineReusePolicy.ReadRecycleRuns();
    private static ScriptEngine? _engine;
    private static ScriptScope? _engineResetScope;
    private static RedirectingStream? _engineOutput;
    private static RedirectingStream? _engineError;
    private static string? _engineDocumentKey;
    private static int _engineRuns;
    // True only after the end-of-run reset of the last read-mode script succeeded inside its read guard.
    private static bool _engineClean;

    // Runs in a private scope at the end of every read-mode run, while that run's read guard is still open:
    // flushes what the script left buffered, then puts back stdout, stderr and sys.path in case the script
    // replaced them. Anything the script left behind that runs here (a custom flush, a hooked sys.path) runs
    // inside the guard, so a model change is rolled back and reported as a read-mode violation. No Python runs
    // between runs or before the next run's guard starts. Written for both IronPython 2.7 and 3.4.
    private const string ResetScript =
        "import sys\n" +
        "for _amb_stream in (sys.stdout, sys.stderr):\n" +
        "    try:\n" +
        "        _amb_stream.flush()\n" +
        "    except Exception:\n" +
        "        pass\n" +
        "sys.stdout = _amb_stdout\n" +
        "sys.stderr = _amb_stderr\n" +
        "sys.stdout.flush()\n" +
        "sys.stderr.flush()\n" +
        "sys.path[:] = _amb_sys_path\n";

    private static ScriptEngine AcquireEngine(Document doc, Stream output, Stream error, string mode)
    {
        var documentKey = DocumentKey(doc);
        if (_engine != null && PythonEngineReusePolicy.RecycleReason(_engineRuns, RecycleRuns, _engineDocumentKey, documentKey) != null)
        {
            ShutdownEngine();
        }

        // A write-mode script always gets a fresh engine (and it is shut down after the run): state a read-mode
        // script left in a shared engine must never run inside an approved write. An engine whose end-of-run
        // reset did not succeed is never reused.
        if (_engine != null && (mode == ModeWrite || !_engineClean))
        {
            ShutdownEngine();
        }

        if (_engine == null)
        {
            StartEngine(documentKey);
        }

        _engineOutput!.Target = output;
        _engineError!.Target = error;
        _engineRuns++;
        _engineClean = false;
        return _engine!;
    }

    private static void StartEngine(string documentKey)
    {
        var engine = PythonEngineFactory.Create();
        try
        {
            // Pre-load Revit assemblies so the script can use "from Autodesk.Revit.DB import *"
            engine.Runtime.LoadAssembly(typeof(Document).Assembly);       // RevitAPI.dll
            engine.Runtime.LoadAssembly(typeof(UIApplication).Assembly);  // RevitAPIUI.dll

            var output = new RedirectingStream();
            var error = new RedirectingStream();
            engine.Runtime.IO.SetOutput(output, Encoding.UTF8);
            engine.Runtime.IO.SetErrorOutput(error, Encoding.UTF8);

            var resetScope = engine.CreateScope();
            // Keep the stream objects the engine was started with (they write to the RedirectingStreams), so the
            // reset can put them back without relying on sys.__stdout__.
            engine.Execute("import sys\n_amb_sys_path = list(sys.path)\n_amb_stdout = sys.stdout\n_amb_stderr = sys.stderr\n", resetScope);

            _engine = engine;
            _engineResetScope = resetScope;
            _engineOutput = output;
            _engineError = error;
            _engineDocumentKey = documentKey;
            _engineRuns = 0;
            _engineClean = false;
        }
        catch
        {
            PythonEngineFactory.ShutdownQuietly(engine);
            throw;
        }
    }

    /// <summary>Detaches this run's streams and shuts the engine down if the run asked for that.</summary>
    private static void ReleaseEngine(ScriptEngine? engine, bool drop)
    {
        if (engine == null || !ReferenceEquals(engine, _engine))
        {
            // Not the warm engine (should not happen): never leave it running.
            PythonEngineFactory.ShutdownQuietly(engine);
            return;
        }
        if (_engineOutput != null) _engineOutput.Target = Stream.Null;
        if (_engineError != null) _engineError.Target = Stream.Null;
        // At the run limit the engine is shut down now instead of idling until the next script, so
        // AEC_BRIDGE_PYTHON_RECYCLE_RUNS=1 behaves like the old one-engine-per-script runner (the opt-out).
        if (drop || !_engineClean || _engineRuns >= RecycleRuns) ShutdownEngine();
    }

    /// <summary>
    /// End-of-run reset for a read-mode run, called while its read guard is still open (#286 review): the only
    /// place script-controlled Python runs outside the script itself, so the guard rolls back and reports any
    /// model change it makes. Marks the engine reusable only when the reset succeeds. Write-mode runs are never
    /// reset: their engine is shut down after the run.
    /// </summary>
    private static void ResetInsideGuard(ScriptEngine? engine, string mode)
    {
        if (mode != ModeRead || engine == null || !ReferenceEquals(engine, _engine) || _engineResetScope == null) return;
        try
        {
            engine.Execute(ResetScript, _engineResetScope);
            _engineClean = true;
        }
        catch
        {
            _engineClean = false;
        }
    }

    /// <summary>Shuts the warm engine down; the next script starts a new one. Never throws. Call on the Revit thread.</summary>
    internal static void ShutdownEngine()
    {
        var engine = _engine;
        _engine = null;
        _engineResetScope = null;
        _engineOutput = null;
        _engineError = null;
        _engineDocumentKey = null;
        _engineRuns = 0;
        _engineClean = false;
        PythonEngineFactory.ShutdownQuietly(engine);
    }

    private static bool IsEngineFatal(Exception ex)
    {
        return ex is OutOfMemoryException
            || ex is InsufficientExecutionStackException
            || ex is InvalidProgramException;
    }

    private static string DocumentKey(Document doc)
    {
        try { return doc.Title + "|" + doc.PathName; }
        catch { return ""; }
    }

    internal static object Run(UIApplication app, Document doc, string script, string? requestedMode)
    {
        var mode = NormalizeMode(requestedMode);
        var progress = new ProgressBuffer(MaxProgressLines, MaxProgressLineLength);

        if (mode == ModeRead)
        {
            var violations = FindReadModeViolations(script);
            if (violations.Count > 0)
            {
                return Result(false, "", "Read mode refuses scripts that could change the model (found: "
                    + string.Join(", ", violations)
                    + "). Use mode='write' with an approved plan for scripts that open transactions.",
                    mode, progress, "read_mode_violation", 0, null);
            }
        }

        var outputMs = new MemoryStream();
        var errorMs = new MemoryStream();
        object? runtime = null;
        ScriptEngine? engine = null;
        ScriptScope? scope = null;
        var dropEngine = false;
        var changedCount = 0;
        var savesBlocked = 0;
        var scriptWarnings = new List<BridgeFailureMessage>();
        EventHandler<DocumentChangedEventArgs>? onChanged = null;
        EventHandler<DocumentSavingEventArgs>? onSaving = null;
        EventHandler<DocumentSavingAsEventArgs>? onSavingAs = null;
        TransactionGroup? readGuard = null;

        try
        {
            // The warm engine (Revit assemblies already loaded) with its stdout and stderr pointed at this run's streams.
            engine = AcquireEngine(doc, outputMs, errorMs, mode);
            runtime = PythonEngineFactory.Describe(engine, _engineRuns);

            // A new scope per run: variables set by one script are absent in the next.
            scope = engine.CreateScope();
            scope.SetVariable("doc", doc);
            scope.SetVariable("uidoc", app.ActiveUIDocument);
            scope.SetVariable("uiapp", app);
            scope.SetVariable("app", app.Application);
            scope.SetVariable("__output__", "");
            scope.SetVariable("__mode__", mode);
            scope.SetVariable("progress", new Action<object?>(progress.Add));
            if (mode == ModeWrite)
            {
                // IronPython cannot subclass IFailuresPreprocessor, so scripts get a ready-made one:
                //   t = amb_transaction(doc, "name"); t.Start(); ...; t.CommitChecked()
                // Warnings are dismissed (no dialog) and returned in the result's "warnings"; errors roll back.
                scope.SetVariable("amb_transaction", new Func<Document, string, BridgeTransaction>(
                    (d, name) => new BridgeTransaction(d, name, messages => scriptWarnings.AddRange(messages))));
            }

            if (mode == ModeRead)
            {
                onChanged = (_, e) =>
                    changedCount += e.GetAddedElementIds().Count + e.GetModifiedElementIds().Count + e.GetDeletedElementIds().Count;
                onSaving = (_, e) => { savesBlocked++; e.Cancel(); };
                onSavingAs = (_, e) => { savesBlocked++; e.Cancel(); };
                app.Application.DocumentChanged += onChanged;
                app.Application.DocumentSaving += onSaving;
                app.Application.DocumentSavingAs += onSavingAs;

                // The name check above only catches scripts that spell out Transaction. A script that builds the name
                // at run time (seen live on Revit 2024: getattr(DB, 'Trans' + 'action')) changed the model without
                // approval. Everything a read-mode script does therefore runs inside a group that is always rolled back.
                readGuard = new TransactionGroup(doc, "AEC Model Bridge read-mode guard");
                readGuard.Start();
            }

            ActiveProgress = progress;
            engine.Execute(script, scope);
            FlushStandardStreams(engine, scope);

            outputMs.Position = 0;
            var output = new StreamReader(outputMs, Encoding.UTF8).ReadToEnd();

            // Also honour __output__ if the script set it explicitly
            if (scope.TryGetVariable("__output__", out object outVar) && outVar is string outStr && !string.IsNullOrEmpty(outStr))
                output = string.IsNullOrEmpty(output) ? outStr : outStr + "\n" + output;

            // A script that started a transaction and never committed it would block the next command
            // ("a transaction is already open"). Roll it back and say so instead of reporting success.
            var left = RollBackOpenTransactions(doc, scope);
            if (left.RolledBack > 0)
            {
                dropEngine = true;
                return Result(false, output,
                    "The script ended with a transaction still open (started, never committed). It was rolled back, so its changes were discarded."
                    + (left.StillOpen ? " The document still reports an open transaction that the bridge cannot reach; check Revit before continuing." : "")
                    + " Commit inside the script, or use 'with Transaction(...) as t:' and call t.Commit().",
                    mode, progress, "transaction_left_open", changedCount, runtime, left.RolledBack);
            }

            ResetInsideGuard(engine, mode);
            var guardNote = EndReadGuard(ref readGuard, app, onChanged, ref changedCount);
            if (changedCount > 0 || savesBlocked > 0)
            {
                dropEngine = true;
                return Result(false, output,
                    $"Read-mode violation: the script touched the model ({changedCount} element changes, {savesBlocked} save attempts blocked). "
                    + guardNote,
                    mode, progress, "read_mode_violation", changedCount, runtime);
            }
            if (guardNote.Length > 0)
            {
                dropEngine = true;
                return Result(false, output, guardNote, mode, progress, "read_mode_guard_failed", changedCount, runtime);
            }

            return BridgeTransactionResults.AppendWarnings(
                Result(true, output, "", mode, progress, null, 0, runtime), scriptWarnings);
        }
        catch (Exception ex) when (engine == null)
        {
            // AcquireEngine failed: no script ran. Say why instead of returning a bare message.
            return Result(false, "", PythonEngineFailure.Describe(ex), mode, progress,
                PythonEngineFailure.EngineUnavailableKind, 0, PythonEngineFailure.Unavailable());
        }
        catch (Exception ex)
        {
            string error;
            try
            {
                FlushStandardStreams(engine, scope);
                errorMs.Position = 0;
                var errText = new StreamReader(errorMs, Encoding.UTF8).ReadToEnd();
                error = string.IsNullOrEmpty(errText) ? ex.Message : errText + "\n" + ex.Message;
            }
            catch
            {
                error = ex.Message;
            }
            var left = RollBackOpenTransactions(doc, scope);
            ResetInsideGuard(engine, mode);
            var guardNote = EndReadGuard(ref readGuard, app, onChanged, ref changedCount);
            if (guardNote.Length > 0) error += Environment.NewLine + guardNote;
            var kind = changedCount > 0 || savesBlocked > 0 ? "read_mode_violation" : null;
            if (left.RolledBack > 0 || left.StillOpen)
            {
                error += $"\nThe failed script left {left.RolledBack} transaction(s) open; they were rolled back so the next command can run."
                    + (left.StillOpen ? " The document still reports an open transaction that the bridge could not reach." : "");
                kind ??= "transaction_left_open";
            }
            if (!PythonEngineFactory.StandardLibraryAvailable && error.Contains("No module named"))
                error += "\n" + PythonEngineFactory.MissingLibraryWarning;
            // An ordinary Python error leaves the engine usable (the next run's reset checks that). Drop it when
            // the script misbehaved or the failure may have left the runtime in a bad state.
            dropEngine = PythonEngineReusePolicy.RecycleAfterResult(kind) || IsEngineFatal(ex);
            return Result(false, "", error, mode, progress, kind, changedCount, runtime, left.RolledBack);
        }
        finally
        {
            ActiveProgress = null;
            if (readGuard != null)
            {
                int unused = 0;
                EndReadGuard(ref readGuard, app, onChanged, ref unused);
            }
            // The engine stays warm for the next script (#286); this run's streams are detached from it, and it
            // is shut down here when the run asked for that (see ReleaseEngine).
            ReleaseEngine(engine, dropEngine);
            if (onChanged != null) app.Application.DocumentChanged -= onChanged;
            if (onSaving != null) app.Application.DocumentSaving -= onSaving;
            if (onSavingAs != null) app.Application.DocumentSavingAs -= onSavingAs;
        }
    }

    /// <summary>
    /// IronPython 3 keeps sys.stdout/sys.stderr text that does not end in a newline in its own buffer, so
    /// print("a", end="") or a final sys.stdout.write("x") never reached the MemoryStream. Flush before reading.
    /// </summary>
    private static void FlushStandardStreams(ScriptEngine? engine, ScriptScope? scope)
    {
        if (engine == null || scope == null) return;
        try { engine.Execute("import sys\nsys.stdout.flush()\nsys.stderr.flush()", scope); }
        catch { /* the script may have replaced sys.stdout; its own output is still returned */ }
    }

    /// <summary>
    /// Closes the read-mode guard group by rolling it back, so nothing a read-mode script did stays in the model.
    /// The change counter is frozen first (the roll-back itself raises DocumentChanged). Returns a sentence for the
    /// result, empty when nothing needs saying.
    /// </summary>
    private static string EndReadGuard(ref TransactionGroup? guard, UIApplication app,
        EventHandler<DocumentChangedEventArgs>? onChanged, ref int changedCount)
    {
        if (guard == null) return "";
        var group = guard;
        guard = null;
        if (onChanged != null) app.Application.DocumentChanged -= onChanged;
        try
        {
            if (group.IsValidObject && group.GetStatus() == TransactionStatus.Started)
            {
                group.RollBack();
                return changedCount > 0
                    ? "The bridge rolled those changes back; the model is as it was. Use mode='write' with an approved plan for scripts that change the model."
                    : "";
            }
            return changedCount > 0
                ? "The read-mode guard group was already closed by the script, so the changes could not be rolled back; check the model."
                : "The read-mode guard group was closed by the script; nothing was rolled back. Check the model before relying on this result.";
        }
        catch (Exception ex)
        {
            return "The read-mode guard could not be rolled back (" + ex.Message + "); check the model.";
        }
    }

    /// <summary>
    /// Rolls back transactions the script left started. Revit has no list of open transactions, so this
    /// looks at the objects the script kept in its top-level variables (and one level into lists, tuples
    /// and dictionaries): sub-transactions first, then transactions, then groups. A transaction held only
    /// in a function's local variable cannot be found; <c>StillOpen</c> reports that case.
    /// </summary>
    internal static (int RolledBack, bool StillOpen) RollBackOpenTransactions(Document doc, ScriptScope? scope)
    {
        var rolledBack = 0;
        try
        {
            var found = new List<object>();
            if (scope != null)
            {
                foreach (var item in scope.GetItems())
                {
                    CollectTransactions(item.Value, found, 1);
                }
            }
            foreach (var order in new[] { 0, 1, 2 })
            {
                foreach (var candidate in found)
                {
                    try
                    {
                        if (order == 0 && candidate is SubTransaction sub && sub.IsValidObject && sub.GetStatus() == TransactionStatus.Started)
                        {
                            sub.RollBack();
                            rolledBack++;
                        }
                        else if (order == 1 && candidate is BridgeTransaction bridgeTx && bridgeTx.GetStatus() == TransactionStatus.Started)
                        {
                            bridgeTx.RollBack();
                            rolledBack++;
                        }
                        else if (order == 1 && candidate is Transaction tx && tx.IsValidObject && tx.GetStatus() == TransactionStatus.Started)
                        {
                            tx.RollBack();
                            rolledBack++;
                        }
                        else if (order == 2 && candidate is TransactionGroup group && group.IsValidObject && group.GetStatus() == TransactionStatus.Started)
                        {
                            group.RollBack();
                            rolledBack++;
                        }
                    }
                    catch
                    {
                        // Keep going: the remaining objects may still be reachable.
                    }
                }
            }
        }
        catch
        {
            // Scope enumeration failed; fall through to the IsModifiable check.
        }
        var stillOpen = false;
        try { stillOpen = doc.IsValidObject && doc.IsModifiable; } catch { /* document went away */ }
        return (rolledBack, stillOpen);
    }

    private static void CollectTransactions(object? value, List<object> found, int depth)
    {
        if (value == null) return;
        if (value is Transaction || value is SubTransaction || value is TransactionGroup || value is BridgeTransaction)
        {
            if (!found.Contains(value)) found.Add(value);
            return;
        }
        if (depth <= 0 || value is string) return;
        if (value is System.Collections.IDictionary dict)
        {
            foreach (System.Collections.DictionaryEntry entry in dict) CollectTransactions(entry.Value, found, depth - 1);
        }
        else if (value is System.Collections.IEnumerable items)
        {
            var seen = 0;
            foreach (var entry in items)
            {
                CollectTransactions(entry, found, depth - 1);
                if (++seen >= 1000) break;
            }
        }
    }

    private static object Result(bool success, string output, string error, string mode, ProgressBuffer progress, string? kind, int changedCount, object? runtime, int transactionsRolledBack = 0)
    {
        return new
        {
            success,
            output,
            error,
            mode,
            progress = progress.Snapshot(),
            error_kind = kind,
            model_changes_in_read_mode = changedCount,
            transactions_rolled_back = transactionsRolledBack,
            runtime,
        };
    }
}

/// <summary>Thread-safe, bounded list of progress lines written by progress("...") in a script.</summary>
internal sealed class ProgressBuffer
{
    private readonly object _gate = new();
    private readonly Queue<string> _lines = new();
    private readonly int _maxLines;
    private readonly int _maxLineLength;

    public ProgressBuffer(int maxLines, int maxLineLength)
    {
        _maxLines = maxLines;
        _maxLineLength = maxLineLength;
    }

    public void Add(object? message)
    {
        var text = message?.ToString() ?? "";
        if (text.Length > _maxLineLength) text = text.Substring(0, _maxLineLength);
        lock (_gate)
        {
            _lines.Enqueue(text);
            while (_lines.Count > _maxLines) _lines.Dequeue();
        }
    }

    public string[] Snapshot()
    {
        lock (_gate) return _lines.ToArray();
    }
}
