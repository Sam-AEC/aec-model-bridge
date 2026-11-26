using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using IronPython.Hosting;
using Microsoft.Scripting.Hosting;

#nullable enable

namespace RevitBridge.Bridge;

/// <summary>Initializes only the IronPython dependencies shipped beside the add-in.</summary>
internal static class PythonEngineFactory
{
    private static string AddinDirectory => Path.GetDirectoryName(typeof(PythonEngineFactory).Assembly.Location)!;
    private static string StandardLibraryPath => Path.Combine(AddinDirectory, "Lib");

    /// <summary>True when the packaged pure-Python standard library (Lib/) sits beside the DLL.</summary>
    internal static bool StandardLibraryAvailable =>
        File.Exists(Path.Combine(StandardLibraryPath, "json", "__init__.py"));

    internal const string MissingLibraryWarning =
        "The Lib folder (IronPython standard library) is missing next to the add-in DLL, so imports such as json, " +
        "collections or os fail. Scripts that only use the Revit API and built-in modules still run. " +
        "Redeploy the whole add-in output folder with scripts/deploy-addin.ps1 (copying only the DLL leaves Lib behind).";

    /// <summary>
    /// Creates the engine. A missing Lib folder does not stop Python: the engine starts without the
    /// standard library and <see cref="Describe"/> says so, so a partial deploy costs the imports
    /// that need Lib, not every script. A missing or mismatched IronPython.Modules.dll still fails,
    /// because built-in modules such as time would silently be absent.
    /// </summary>
    public static ScriptEngine Create()
    {
        var modulesPath = Path.Combine(AddinDirectory, "IronPython.Modules.dll");
        if (!File.Exists(modulesPath))
            throw new FileNotFoundException(
                "Bundled IronPython dependencies are incomplete. Reinstall the matching add-in including IronPython.Modules.dll and Lib.");

        var modulesName = AssemblyName.GetAssemblyName(modulesPath);
        if (modulesName.Name != "IronPython.Modules" ||
            modulesName.Version != typeof(Python).Assembly.GetName().Version)
            throw new InvalidOperationException("Bundled IronPython.Modules.dll does not match the loaded IronPython engine version.");

        // Revit's application base is not the add-in directory. IronPython's
        // name-based load silently omits built-in modules such as time if this
        // assembly is not resolved. Load the shipped assembly before creating it.
        Assembly.LoadFrom(modulesPath);
        var engine = Python.CreateEngine();
        try
        {
            var libraryAvailable = StandardLibraryAvailable;
            if (libraryAvailable)
            {
                var paths = new List<string>(engine.GetSearchPaths());
                paths.Insert(0, StandardLibraryPath);
                engine.SetSearchPaths(paths);
            }
            // Report availability only after both pure-Python and built-in imports work.
            engine.Execute(libraryAvailable ? "import json, time" : "import time");
            return engine;
        }
        catch
        {
            ShutdownQuietly(engine);
            throw;
        }
    }

    // IronPython 3 builds sys.stdout and sys.stderr when the engine is created, from the console encoding.
    // A process without a console (Revit on .NET 8/10) gets UTF-16LE there, and a later
    // Runtime.IO.SetOutput(stream, UTF8) only swaps the byte stream underneath. Wrap the same byte
    // buffers again as UTF-8 text. IronPython 2.7 has no .buffer and already honours SetOutput.
    private const string Utf8StreamsScript =
        "import sys, io\n" +
        "if hasattr(sys.stdout, 'buffer'):\n" +
        "    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='strict', line_buffering=True)\n" +
        "if hasattr(sys.stderr, 'buffer'):\n" +
        "    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='backslashreplace', line_buffering=True)\n";

    /// <summary>Call after SetOutput/SetErrorOutput and before anything captures sys.stdout.</summary>
    public static void UseUtf8StandardStreams(ScriptEngine engine) =>
        engine.Execute(Utf8StreamsScript, engine.CreateScope());

    /// <summary>
    /// Text from the captured stream bytes: UTF-8, unless most odd bytes are NUL (UTF-16LE), so output
    /// never reaches the client with a NUL after every character.
    /// </summary>
    public static string DecodeOutput(byte[] bytes)
    {
        // Encoding.UTF8 writers emit a BOM first; StreamReader used to drop it, so keep dropping it.
        var start = bytes.Length >= 3 && bytes[0] == 0xEF && bytes[1] == 0xBB && bytes[2] == 0xBF ? 3
            : bytes.Length >= 2 && bytes[0] == 0xFF && bytes[1] == 0xFE ? 2 : 0;
        var count = bytes.Length - start;
        if (count >= 2 && count % 2 == 0)
        {
            var nulOdd = 0;
            for (var i = start + 1; i < bytes.Length; i += 2)
                if (bytes[i] == 0) nulOdd++;
            if (nulOdd * 4 >= count / 2 * 3)
                return System.Text.Encoding.Unicode.GetString(bytes, start, count);
        }
        return System.Text.Encoding.UTF8.GetString(bytes, start, count);
    }

    /// <summary>Ends the engine's runtime; never throws. PythonScriptRunner calls it when it recycles its warm engine.</summary>
    public static void ShutdownQuietly(ScriptEngine? engine)
    {
        if (engine == null) return;
        try { engine.Runtime.Shutdown(); }
        catch { /* a failed shutdown must not hide the script's own result */ }
    }

    /// <param name="engineRun">Which script this is on the engine (1 = the engine was started for it); 0 when not known.</param>
    public static object Describe(ScriptEngine engine, int engineRun = 0)
    {
        var available = StandardLibraryAvailable;
        return new
        {
            engine = "IronPython",
            version = engine.LanguageVersion.ToString(),
            standard_library_available = available,
            standard_library_path = StandardLibraryPath,
            standard_library_warning = available ? null : MissingLibraryWarning,
            verified_modules = available ? new[] { "json", "time" } : new[] { "time" },
            engine_run = engineRun
        };
    }
}
