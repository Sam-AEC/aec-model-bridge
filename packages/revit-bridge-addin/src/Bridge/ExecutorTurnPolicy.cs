using System;

namespace RevitBridge.Bridge;

/// <summary>
/// Rules for how much work one ExternalEvent turn may do (#287) and when the optional Idling wake is
/// attached (#288). Kept free of Revit types so packages/revit-bridge-addin-tests can test them.
/// </summary>
public static class ExecutorTurnPolicy
{
    public const string BudgetVariable = "AEC_BRIDGE_TURN_BUDGET_MS";
    public const string FastWakeVariable = "AEC_BRIDGE_FAST_WAKE";
    public const int DefaultBudgetMs = 40;
    public const int MaxBudgetMs = 200;

    /// <summary>Turn budget in ms from the environment: default 40, clamped to 0-200. 0 means one request per turn.</summary>
    public static int ReadBudgetMs()
    {
        return ParseBudgetMs(Environment.GetEnvironmentVariable(BudgetVariable));
    }

    public static int ParseBudgetMs(string? raw)
    {
        if (!int.TryParse(raw?.Trim(), out var value)) return DefaultBudgetMs;
        return Math.Min(MaxBudgetMs, Math.Max(0, value));
    }

    /// <summary>True only when AEC_BRIDGE_FAST_WAKE is 1 or true. Off by default.</summary>
    public static bool ReadFastWake()
    {
        return ParseFastWake(Environment.GetEnvironmentVariable(FastWakeVariable));
    }

    public static bool ParseFastWake(string? raw)
    {
        var value = raw?.Trim();
        return value == "1" || string.Equals(value, "true", StringComparison.OrdinalIgnoreCase);
    }

    /// <summary>
    /// Whether a request for this tool may share a turn with other requests. Only commands marked read-only
    /// (BridgeCommand IsMutating = false) qualify, and not the read-only commands that can run for seconds
    /// (exports, snapshot, clash check). Writes and unknown tools always run alone.
    /// </summary>
    public static bool MayShareTurn(string? tool, Func<string, bool> isReadOnly)
    {
        if (string.IsNullOrEmpty(tool)) return false;
        var name = tool!;
        if (!isReadOnly(name)) return false;
        if (name.StartsWith("revit.export_", StringComparison.Ordinal)) return false;
        return name != "revit.extract_snapshot" && name != "revit.check_clashes";
    }

    /// <summary>
    /// Whether the turn may take another request after <paramref name="ranSoFar"/> requests have run.
    /// The budget is checked before each further request, so a turn lasts at most the budget plus one command.
    /// </summary>
    public static bool MayTakeAnother(int ranSoFar, bool lastSharedTurn, long elapsedMs, int budgetMs)
    {
        if (ranSoFar == 0) return true;
        return lastSharedTurn && budgetMs > 0 && elapsedMs < budgetMs;
    }
}

/// <summary>
/// Tracks whether the Idling wake handler is attached. It is attached only while requests are queued, so
/// Revit's idle CPU use stays at zero when the bridge has nothing to do.
/// </summary>
public sealed class FastWakeGate
{
    public FastWakeGate(bool enabled)
    {
        Enabled = enabled;
    }

    public bool Enabled { get; }
    public bool Attached { get; private set; }

    /// <summary>True when the caller should attach the handler now (enabled, not attached, work queued).</summary>
    public bool ShouldAttach(int queued)
    {
        if (!Enabled || Attached || queued <= 0) return false;
        Attached = true;
        return true;
    }

    /// <summary>True when the caller should detach the handler now (attached and the queue is empty).</summary>
    public bool ShouldDetach(int queued)
    {
        if (!Attached || queued > 0) return false;
        Attached = false;
        return true;
    }

    /// <summary>For when attaching failed or the handler was removed some other way.</summary>
    public void MarkDetached()
    {
        Attached = false;
    }
}
