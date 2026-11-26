using System;
using System.IO;

namespace RevitBridge.Bridge;

/// <summary>
/// When the warm IronPython engine (#286) must be replaced by a new one. Kept free of Revit and IronPython
/// types so packages/revit-bridge-addin-tests can test it. Used by <see cref="PythonScriptRunner"/>.
/// </summary>
public static class PythonEngineReusePolicy
{
    public const string RecycleRunsVariable = "AEC_BRIDGE_PYTHON_RECYCLE_RUNS";
    public const int DefaultRecycleRuns = 50;
    public const int MaxRecycleRuns = 10000;

    /// <summary>Runs per engine from the environment: default 50, clamped to 1-10000. 1 means a new engine every run.</summary>
    public static int ReadRecycleRuns()
    {
        return ParseRecycleRuns(Environment.GetEnvironmentVariable(RecycleRunsVariable));
    }

    public static int ParseRecycleRuns(string? raw)
    {
        if (!int.TryParse(raw?.Trim(), out var value)) return DefaultRecycleRuns;
        return Math.Min(MaxRecycleRuns, Math.Max(1, value));
    }

    /// <summary>
    /// The reason the current engine must not run the next script, or null when it may.
    /// <paramref name="runsSoFar"/> counts scripts the engine has already run.
    /// </summary>
    public static string? RecycleReason(int runsSoFar, int recycleRuns, string? engineDocumentKey, string documentKey)
    {
        if (runsSoFar >= Math.Max(1, recycleRuns)) return "run_limit";
        if (!string.Equals(engineDocumentKey, documentKey, StringComparison.Ordinal)) return "document_changed";
        return null;
    }

    /// <summary>
    /// True when a script result means the engine should be dropped after the run: the script touched the
    /// model in read mode or left a transaction open, so any state it left behind is not trusted.
    /// </summary>
    public static bool RecycleAfterResult(string? errorKind)
    {
        return errorKind == "read_mode_violation"
            || errorKind == "read_mode_guard_failed"
            || errorKind == "transaction_left_open";
    }
}

/// <summary>
/// A write-only stream that forwards to a target that can be swapped. The warm engine is given one of these
/// for stdout and one for stderr when it starts; each run points them at its own fresh MemoryStream, and
/// between runs they point at Stream.Null, so no output reaches the wrong run.
/// </summary>
public sealed class RedirectingStream : Stream
{
    private Stream _target = Stream.Null;

    public Stream Target
    {
        get => _target;
        set => _target = value ?? Stream.Null;
    }

    public override bool CanRead => false;
    public override bool CanSeek => _target.CanSeek;
    public override bool CanWrite => true;
    public override long Length => _target.Length;

    public override long Position
    {
        get => _target.Position;
        set => _target.Position = value;
    }

    public override void Flush() => _target.Flush();
    public override int Read(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    public override long Seek(long offset, SeekOrigin origin) => _target.Seek(offset, origin);
    public override void SetLength(long value) => _target.SetLength(value);
    public override void Write(byte[] buffer, int offset, int count) => _target.Write(buffer, offset, count);
}
