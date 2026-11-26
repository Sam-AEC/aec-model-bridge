using System;
using System.Runtime.InteropServices;
using System.Text;

#nullable enable

namespace RevitBridge.Bridge;

/// <summary>
/// Turns an exception thrown while the IronPython engine starts into a short ASCII message with the exception
/// types, so a failure such as a bare "Error" names its cause. Kept free of Revit and IronPython types so
/// packages/revit-bridge-addin-tests can test it. Used by <see cref="PythonScriptRunner"/>.
/// </summary>
public static class PythonEngineFailure
{
    public const string EngineUnavailableKind = "engine_unavailable";
    private const int MaxDepth = 4;
    private const int MaxLength = 800;

    public static string Describe(Exception ex)
    {
        var text = new StringBuilder("The Python engine could not start. ");
        var current = ex;
        for (var depth = 0; current != null && depth < MaxDepth; depth++, current = current.InnerException!)
        {
            if (depth > 0) text.Append(" <- ");
            text.Append(current.GetType().Name).Append(": ").Append(current.Message);
        }
        var ascii = new StringBuilder(text.Length);
        foreach (var ch in text.ToString())
            ascii.Append(ch >= ' ' && ch <= '~' ? ch : ' ');
        var result = ascii.ToString();
        return result.Length > MaxLength ? result.Substring(0, MaxLength) : result;
    }

    /// <summary>Result "runtime" for a failed start: which host runtime the add-in is running on.</summary>
    public static object Unavailable()
    {
        return new { engine = "IronPython", available = false, host_runtime = RuntimeInformation.FrameworkDescription };
    }
}
