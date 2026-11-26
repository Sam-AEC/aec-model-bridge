using System;
using System.IO;
using System.Text;
using RevitBridge.Bridge;

static class Program
{
    static void Check(bool condition, string message)
    {
        if (!condition) throw new Exception(message);
    }

    static int Main(string[] args)
    {
        var originalDirectory = Directory.GetCurrentDirectory();
        var testDirectory = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "unrelated-working-directory");
        Directory.CreateDirectory(testDirectory);
        File.WriteAllText(Path.Combine(testDirectory, "json.py"), "raise RuntimeError('wrong json library')");
        Directory.SetCurrentDirectory(testDirectory);
        try
        {
            var engine = PythonEngineFactory.Create();
            try
            {
                var scope = engine.CreateScope();
                engine.Execute(
                    "import json, time, collections, os\n" +
                    "assert json.loads(json.dumps({'count': 6}))['count'] == 6\n" +
                    "assert time.time() > 0\n" +
                    "assert collections.Counter(['wall', 'wall'])['wall'] == 2\n" +
                    "assert os.path.basename('villa.png') == 'villa.png'\n" +
                    "result = 'stdlib works'\n", scope);
                Check(scope.GetVariable<string>("result") == "stdlib works", "Real library functions failed");
                Check(engine.LanguageVersion.Major == int.Parse(args[0]), "Unexpected Python language major version");
                Check(engine.LanguageVersion.Minor == int.Parse(args[1]), "Unexpected Python language minor version");
                var description = PythonEngineFactory.Describe(engine);
                var descriptionType = description.GetType();
                Check((bool)descriptionType.GetProperty("standard_library_available").GetValue(description, null),
                    "Verified standard library should be reported available");
                Check((string)descriptionType.GetProperty("version").GetValue(description, null) == engine.LanguageVersion.ToString(),
                    "Reported runtime version must match the actual engine");
                Console.WriteLine("PASS: real IronPython " + engine.LanguageVersion +
                    " imports json/time/collections/os from bundled dependencies, executes their functions, and ignores working-directory json.py.");
            }
            finally
            {
                engine.Runtime.Shutdown();
            }

            var libraryPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Lib");
            var hiddenLibrary = libraryPath + "-missing-test";
            Directory.Move(libraryPath, hiddenLibrary);
            try
            {
                // A deploy that left Lib behind must degrade, not disable Python: the engine starts,
                // built-in modules and the Revit-style API work, imports that need Lib fail clearly,
                // and Describe says the standard library is unavailable.
                var degraded = PythonEngineFactory.Create();
                try
                {
                    var scope = degraded.CreateScope();
                    degraded.Execute("import time\nresult = 'builtin ok' if time.time() > 0 else 'bad'", scope);
                    Check(scope.GetVariable<string>("result") == "builtin ok", "Built-in modules must work without Lib");
                    var failedImport = false;
                    try { degraded.Execute("import json", degraded.CreateScope()); }
                    catch (Exception) { failedImport = true; }
                    Check(failedImport, "import json must fail when Lib is missing");
                    var description = PythonEngineFactory.Describe(degraded);
                    var descriptionType = description.GetType();
                    Check(!(bool)descriptionType.GetProperty("standard_library_available").GetValue(description, null),
                        "Missing Lib must be reported as unavailable");
                    var warning = (string)descriptionType.GetProperty("standard_library_warning").GetValue(description, null);
                    Check(warning != null && warning.Contains("deploy-addin.ps1"), "Missing Lib warning should name the fix");
                }
                finally
                {
                    PythonEngineFactory.ShutdownQuietly(degraded);
                }
            }
            finally
            {
                Directory.Move(hiddenLibrary, libraryPath);
            }
            Console.WriteLine("PASS: missing packaged standard library degrades (built-ins work, import json fails, runtime reports it).");

            // Shutting the runtime down after a script must leave the next engine independent.
            var first = PythonEngineFactory.Create();
            first.Execute("leaked = 41", first.CreateScope());
            PythonEngineFactory.ShutdownQuietly(first);
            PythonEngineFactory.ShutdownQuietly(first); // twice is harmless
            var second = PythonEngineFactory.Create();
            try
            {
                var scope = second.CreateScope();
                second.Execute("import json\nresult = json.dumps({'a': 1})", scope);
                Check(scope.GetVariable<string>("result") == "{\"a\": 1}", "A fresh engine after shutdown must work");
            }
            finally
            {
                PythonEngineFactory.ShutdownQuietly(second);
            }
            Console.WriteLine("PASS: runtime shutdown after a script leaves the next engine working.");

            // #406: with no console (Revit on .NET 8/10) sys.stdout starts as UTF-16LE; output must still be UTF-8.
            var consoleOut = Console.Out;
            Console.SetOut(TextWriter.Null);
            var capture = PythonEngineFactory.Create();
            try
            {
                var stdout = new MemoryStream();
                var stderr = new MemoryStream();
                capture.Runtime.IO.SetOutput(stdout, Encoding.UTF8);
                capture.Runtime.IO.SetErrorOutput(stderr, Encoding.UTF8);
                if (int.Parse(args[0]) >= 3) PythonEngineFactory.UseUtf8StandardStreams(capture);
                var scope = capture.CreateScope();
                capture.Execute("import sys\nprint('box' + (' \\u00e9' if sys.version_info[0] >= 3 else ''))\nsys.stderr.write('err')\nsys.stdout.flush()\nsys.stderr.flush()", scope);
                var expected = int.Parse(args[0]) >= 3 ? "box é" : "box";
                Check(PythonEngineFactory.DecodeOutput(stdout.ToArray()).TrimEnd() == expected, "print must come back as UTF-8 text");
                Check(Array.IndexOf(stdout.ToArray(), (byte)0) < 0, "stdout bytes must not contain NULs");
                Check(PythonEngineFactory.DecodeOutput(stderr.ToArray()) == "err", "stderr must come back as UTF-8 text");
            }
            finally
            {
                PythonEngineFactory.ShutdownQuietly(capture);
                Console.SetOut(consoleOut);
            }
            Check(PythonEngineFactory.DecodeOutput(Encoding.Unicode.GetBytes("box")) == "box", "UTF-16LE bytes must decode");
            Check(PythonEngineFactory.DecodeOutput(Encoding.UTF8.GetBytes("box é")) == "box é", "UTF-8 bytes must decode");
            Console.WriteLine("PASS: print(\"box\") returns UTF-8 text without NULs when the process has no console.");

            var modulesPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "IronPython.Modules.dll");
            var hiddenModules = modulesPath + "-missing-test";
            File.Move(modulesPath, hiddenModules);
            try
            {
                try
                {
                    PythonEngineFactory.Create();
                    throw new Exception("Missing built-in modules should fail initialization");
                }
                catch (FileNotFoundException error)
                {
                    Check(error.Message.Contains("Bundled IronPython dependencies are incomplete"), "Missing modules error should be actionable");
                }
                File.Copy(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "IronPython.dll"), modulesPath);
                try
                {
                    PythonEngineFactory.Create();
                    throw new Exception("Mismatched built-in module assembly should fail initialization");
                }
                catch (InvalidOperationException error)
                {
                    Check(error.Message.Contains("does not match"), "Mismatched modules error should be actionable");
                }
            }
            finally
            {
                if (File.Exists(modulesPath)) File.Delete(modulesPath);
                File.Move(hiddenModules, modulesPath);
            }
            Console.WriteLine("PASS: missing or mismatched built-in module assembly fails clearly.");
            return 0;
        }
        catch (Exception error)
        {
            Console.WriteLine("FAIL: " + error);
            return 1;
        }
        finally
        {
            Directory.SetCurrentDirectory(originalDirectory);
        }
    }
}
