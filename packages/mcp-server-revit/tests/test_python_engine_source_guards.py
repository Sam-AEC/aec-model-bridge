"""Source guards for the add-in's IronPython engine (no Revit needed).

These read the C# and PowerShell sources, so they catch a regression in what ships
but prove nothing about the loaded add-in; scripts/test-ironpython-runtime.ps1 runs
the engine itself against a build.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ADDIN = REPO_ROOT / "packages" / "revit-bridge-addin"
FACTORY = (ADDIN / "src" / "Bridge" / "PythonEngineFactory.cs").read_text(encoding="utf-8")
RUNNER = (ADDIN / "src" / "Bridge" / "PythonScriptRunner.cs").read_text(encoding="utf-8")
COMMANDS = (ADDIN / "src" / "Bridge" / "BridgeCommandFactory.cs").read_text(encoding="utf-8")
CSPROJ = (ADDIN / "RevitBridge.csproj").read_text(encoding="utf-8")
RUNTIME_SCRIPT = (REPO_ROOT / "scripts" / "test-ironpython-runtime.ps1").read_text(encoding="utf-8")


def _package_versions(name: str) -> dict[str, str]:
    """TargetFramework condition -> version for one PackageReference."""
    found = {}
    for match in re.finditer(rf'<PackageReference Include="{re.escape(name)}" Version="([^"]+)" Condition="([^"]+)"', CSPROJ):
        found["net48" if "=='net48'" in match.group(2) and "!=" not in match.group(2) else "other"] = match.group(1)
    return found


def test_stdlib_package_is_referenced_and_matches_ironpython():
    assert _package_versions("IronPython.StdLib") == _package_versions("IronPython")
    assert len(_package_versions("IronPython.StdLib")) == 2


def test_engine_adds_the_lib_folder_next_to_the_dll_to_the_search_path():
    assert "SetSearchPaths" in FACTORY
    assert '"Lib"' in FACTORY
    assert "Assembly.Location" in FACTORY


def test_execute_python_goes_through_the_factory_and_nothing_else_creates_an_engine():
    handler = COMMANDS.split('[BridgeCommand("revit.execute_python"', 1)[1].split("[BridgeCommand(", 1)[0]
    assert "PythonScriptRunner.Run(" in handler
    assert 'TryGetProperty("mode"' in handler
    sources = list((ADDIN / "src").rglob("*.cs"))
    creators = [p.name for p in sources if "Python.CreateEngine()" in p.read_text(encoding="utf-8")]
    assert creators == ["PythonEngineFactory.cs"]


def test_read_mode_backstops_and_progress_helper_are_present():
    assert 'scope.SetVariable("progress"' in RUNNER
    assert "DocumentChanged +=" in RUNNER and "DocumentChanged -=" in RUNNER
    assert "e.Cancel()" in RUNNER
    assert "read_mode_violation" in RUNNER
    assert "class ProgressBuffer" in RUNNER
    assert "PythonEngineFactory.Create()" in RUNNER


def test_engine_factory_stays_free_of_revit_references():
    # scripts/test-ironpython-runtime.ps1 compiles this one file outside Revit.
    assert "Autodesk.Revit" not in FACTORY


def test_runtime_script_compiles_the_factory_and_checks_the_bundled_modules():
    assert "PythonEngineFactory.cs" in RUNTIME_SCRIPT
    assert "Lib/json/__init__.py" in RUNTIME_SCRIPT
    assert "throw" in RUNTIME_SCRIPT


DEPLOY_SCRIPT = (REPO_ROOT / "scripts" / "deploy-addin.ps1").read_text(encoding="utf-8")


def test_missing_lib_degrades_instead_of_disabling_python():
    create = FACTORY.split("public static ScriptEngine Create()", 1)[1].split("public static void ShutdownQuietly", 1)[0]
    # only the Modules assembly is still a hard requirement; Lib is optional
    assert 'File.Exists(Path.Combine(StandardLibraryPath, "json"' not in create
    assert "StandardLibraryAvailable" in create
    assert '"import time"' in create
    assert "standard_library_warning" in FACTORY and "deploy-addin.ps1" in FACTORY


def test_runner_keeps_one_warm_engine_with_a_new_scope_per_run():
    """#286: the engine is reused, but every run gets a new scope, its own streams and a reset."""
    text = RUNNER.replace("\r\n", "\n")
    run = text.split("internal static object Run(", 1)[1].split("private static void FlushStandardStreams", 1)[0]
    assert "AcquireEngine(doc, outputMs, errorMs, mode)" in run
    assert "scope = engine.CreateScope();" in run, "a variable set in one run must be absent in the next"
    assert "PythonEngineFactory.Create()" not in run, "Run must not start an engine itself"
    marker = "finally\n        {\n            ActiveProgress = null;"
    finally_block = run.split(marker, 1)[1]
    assert "ReleaseEngine(engine, dropEngine)" in finally_block
    # Revit assemblies are loaded once, when the warm engine starts.
    start = text.split("private static void StartEngine(", 1)[1].split("private static void ReleaseEngine(", 1)[0]
    assert "PythonEngineFactory.Create()" in start
    assert "LoadAssembly(typeof(Document).Assembly)" in start and "LoadAssembly(typeof(UIApplication).Assembly)" in start
    assert "new RedirectingStream()" in start and "SetOutput(" in start and "SetErrorOutput(" in start
    # The reset restores stdout, stderr and sys.path. It runs at the end of a read-mode run, inside the read
    # guard, never when an engine is acquired: no leftover script code runs outside a guard (#286 review).
    acquire = text.split("private static ScriptEngine AcquireEngine(", 1)[1].split("private static void StartEngine(", 1)[0]
    assert "ResetScript" not in acquire and "RecycleReason(" in acquire and "ShutdownEngine()" in acquire
    assert "mode == ModeWrite || !_engineClean" in acquire, "write runs get a fresh engine; an unreset engine is dropped"
    assert "sys.stdout = _amb_stdout" in text and "sys.path[:] = _amb_sys_path" in text
    assert "_amb_stdout = sys.stdout" in start, "the reset restores the streams the engine started with"
    release = text.split("private static void ReleaseEngine(", 1)[1].split("internal static void ShutdownEngine()", 1)[0]
    assert "if (drop || !_engineClean || _engineRuns >= RecycleRuns) ShutdownEngine();" in release, \
        "AEC_BRIDGE_PYTHON_RECYCLE_RUNS=1 must not keep an engine alive between scripts"
    assert "Runtime.Shutdown()" in FACTORY.split("ShutdownQuietly(ScriptEngine? engine)", 1)[1]
    assert "PythonEngineFactory.ShutdownQuietly(engine)" in text.split("internal static void ShutdownEngine()", 1)[1]


def test_warm_engine_reset_runs_inside_the_read_guard():
    """#286 review (P1): a callback a read-mode script leaves behind (a custom sys.stdout.flush) must not run
    outside the read guard, where it could change the model without approval or a violation report."""
    text = RUNNER.replace("\r\n", "\n")
    reset = text.split("private static void ResetInsideGuard(", 1)[1].split("private static", 1)[0]
    assert "mode != ModeRead" in reset and "engine.Execute(ResetScript, _engineResetScope)" in reset
    assert "_engineClean = true;" in reset and "_engineClean = false;" in reset
    run = text.split("internal static object Run(", 1)[1].split("private static void FlushStandardStreams", 1)[0]
    # Both the success path and the error path reset before the guard is ended.
    for path in run.split("catch (Exception ex)", 1):
        assert path.index("ResetInsideGuard(engine, mode);") < path.index("EndReadGuard(ref readGuard")
    assert text.count("engine.Execute(ResetScript") == 1, "the reset must have no other call site"


def test_warm_engine_is_recycled_on_run_limit_document_change_and_misbehaving_scripts():
    policy = (ADDIN / "src" / "Bridge" / "PythonEngineReusePolicy.cs").read_text(encoding="utf-8")
    assert "AEC_BRIDGE_PYTHON_RECYCLE_RUNS" in policy and "DefaultRecycleRuns = 50" in policy
    assert '"run_limit"' in policy and '"document_changed"' in policy
    for kind in ("read_mode_violation", "transaction_left_open"):
        assert f'"{kind}"' in policy
    assert "Autodesk.Revit" not in policy and "IronPython" not in policy.split("namespace", 1)[0]
    text = RUNNER.replace("\r\n", "\n")
    assert text.count("dropEngine = true;") >= 3
    assert "PythonEngineReusePolicy.RecycleAfterResult(kind) || IsEngineFatal(ex)" in text
    app = (ADDIN / "src" / "Bridge" / "App.cs").read_text(encoding="utf-8")
    assert "PythonScriptRunner.ShutdownEngine();" in app


def test_runner_rolls_back_transactions_a_script_left_open():
    text = RUNNER.replace("\r\n", "\n")
    assert "RollBackOpenTransactions(doc, scope)" in text
    # both the failure path and the "script returned but never committed" path
    assert text.count("RollBackOpenTransactions(doc, scope)") >= 2
    for kind in ("SubTransaction", "Transaction", "TransactionGroup"):
        assert f"is {kind} " in text
    assert "TransactionStatus.Started" in text and ".RollBack()" in text
    assert "transaction_left_open" in text and "transactions_rolled_back" in text


def test_deploy_script_mirrors_the_whole_folder_and_verifies_it():
    assert "robocopy" in DEPLOY_SCRIPT and "/MIR" in DEPLOY_SCRIPT
    assert r"C:\ProgramData\AECModelBridge\bin" in DEPLOY_SCRIPT
    assert 'Get-Process -Name "Revit"' in DEPLOY_SCRIPT and "-Force" in DEPLOY_SCRIPT
    assert "backup" in DEPLOY_SCRIPT.lower() and "Restore-Backup" in DEPLOY_SCRIPT
    assert "LastWriteTimeUtc" in DEPLOY_SCRIPT and ".Length" in DEPLOY_SCRIPT
    assert r"Lib\json\__init__.py" in DEPLOY_SCRIPT
    # same exclusions as the installer, which must stay the single layout reference
    iss = (REPO_ROOT / "scripts" / "installer" / "AECModelBridge.iss").read_text(encoding="utf-8")
    for name in ("RevitAPI.dll", "RevitAPIUI.dll", "AdWindows.dll", "AdskLicensingSDK_*.dll"):
        assert name in iss and name in DEPLOY_SCRIPT
