using System;
using System.Diagnostics;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Serilog;

namespace RevitBridge.Bridge;

/// <summary>
/// Ensures the Python MCP hub's panel HTTP shim (packages/mcp-server-revit's
/// panel_server.py) is reachable on 127.0.0.1 before the dockable panel needs it.
///
/// HubClient.cs assumes something is already listening on the panel port — this
/// class is what makes that true on a machine where nobody has manually started
/// `aec-model-bridge-panel-server`. It never manages a hub it didn't start itself:
/// if something is already answering /health (a developer's own instance, or a
/// future bundled-runtime launcher), this leaves it alone entirely, both at
/// startup and at shutdown.
///
/// Python provisioning is not yet bundled with the installer (still open,
/// D-010); this is a best-effort launch matching the interpreter conventions
/// docs/install.md already documents
/// (a project .venv, or a bare `python`/`py` on PATH), not a substitute for that
/// installer work.
/// </summary>
public sealed class PanelHubLauncher
{
    private const int HealthCheckTimeoutMs = 800;
    private const int PostLaunchPollIntervalMs = 500;
    private const int PostLaunchMaxAttempts = 10;

    private static readonly HttpClient HealthClient = new HttpClient { Timeout = TimeSpan.FromMilliseconds(HealthCheckTimeoutMs) };

    private Process? _launchedProcess;

    private static int Port
    {
        get
        {
            var raw = Environment.GetEnvironmentVariable("MCP_PANEL_HTTP_PORT");
            return int.TryParse(raw, out var port) ? port : 8787;
        }
    }

    /// <summary>
    /// Checks whether the panel hub is reachable and launches it in the background
    /// if not. Returns immediately; the check/launch/poll sequence runs on a
    /// background task so it never blocks Revit's OnStartup.
    /// </summary>
    public void EnsureRunning()
    {
        _ = Task.Run(EnsureRunningAsync);
    }

    private async Task EnsureRunningAsync()
    {
        if (await IsHealthyAsync().ConfigureAwait(false))
        {
            Log.Information("Panel hub already reachable on 127.0.0.1:{Port} — not launching a new one", Port);
            return;
        }

        var interpreter = ResolvePythonInterpreter();
        if (interpreter == null)
        {
            Log.Warning(
                "Panel hub is not reachable on 127.0.0.1:{Port} and no Python interpreter could be found to " +
                "launch it. Set AEC_MODEL_BRIDGE_PYTHON to a python.exe, or start it manually with " +
                "'aec-model-bridge-panel-server' / 'python -m revit_mcp_server.panel_server' — see docs/install.md. " +
                "The panel will show a connection error until the hub is reachable.",
                Port);
            return;
        }

        try
        {
            var startInfo = new ProcessStartInfo
            {
                FileName = interpreter,
                Arguments = "-m revit_mcp_server.panel_server",
                UseShellExecute = false,
                CreateNoWindow = true,
                // Do NOT redirect stdout/stderr: redirected but unread pipes deadlock
                // once the subprocess writes more than ~4KB (the pipe buffer). The hub
                // logs at startup so this threshold is reachable. Output is discarded
                // anyway — the health-poll loop is the correct readiness signal (H4 fix).
            };

            _launchedProcess = Process.Start(startInfo);
            Log.Information("Launched panel hub via '{Interpreter} -m revit_mcp_server.panel_server' (pid {Pid})",
                interpreter, _launchedProcess?.Id);
        }
        catch (Exception ex)
        {
            Log.Warning(ex, "Failed to launch the panel hub with interpreter '{Interpreter}'", interpreter);
            return;
        }

        for (var attempt = 0; attempt < PostLaunchMaxAttempts; attempt++)
        {
            await Task.Delay(PostLaunchPollIntervalMs).ConfigureAwait(false);
            if (await IsHealthyAsync().ConfigureAwait(false))
            {
                Log.Information("Panel hub is up on 127.0.0.1:{Port}", Port);
                return;
            }
        }

        Log.Warning(
            "Launched the panel hub but it never became reachable on 127.0.0.1:{Port} after {Attempts} attempts. " +
            "Check %LOCALAPPDATA%\\AECModelBridge or the process's own logs for why it failed to start.",
            Port, PostLaunchMaxAttempts);
    }

    private static async Task<bool> IsHealthyAsync()
    {
        try
        {
            using var response = await HealthClient.GetAsync($"http://127.0.0.1:{Port}/health").ConfigureAwait(false);
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    /// <summary>
    /// Finds a Python interpreter capable of running revit_mcp_server, preferring
    /// an explicit override, then falling back to whatever's on PATH. Does not
    /// search for a project .venv, since the add-in has no reliable way to know
    /// where the hub's source checkout lives once installed — that's exactly the
    /// gap the bundled-runtime installer (D-010) is meant to close.
    /// </summary>
    private static string? ResolvePythonInterpreter()
    {
        var overridePath = Environment.GetEnvironmentVariable("AEC_MODEL_BRIDGE_PYTHON");
        if (!string.IsNullOrWhiteSpace(overridePath))
        {
            return overridePath;
        }

        foreach (var candidate in new[] { "python", "py" })
        {
            if (CanRun(candidate))
            {
                return candidate;
            }
        }

        return null;
    }

    private static bool CanRun(string command)
    {
        try
        {
            using var process = Process.Start(new ProcessStartInfo
            {
                FileName = command,
                Arguments = "--version",
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            });
            process?.WaitForExit(2000);
            return process is { HasExited: true, ExitCode: 0 };
        }
        catch
        {
            return false;
        }
    }

    /// <summary>
    /// Kills the hub process only if this launcher started it — a hub that was
    /// already running before Revit started (a developer's own instance) is left
    /// untouched, matching the same restraint EnsureRunning applies at startup.
    /// </summary>
    public void StopIfLaunched()
    {
        if (_launchedProcess == null)
        {
            return;
        }

        try
        {
            if (!_launchedProcess.HasExited)
            {
                _launchedProcess.Kill();
                Log.Information("Stopped the panel hub process this launcher started (pid {Pid})", _launchedProcess.Id);
            }
        }
        catch (Exception ex)
        {
            Log.Warning(ex, "Failed to stop the panel hub process cleanly");
        }
        finally
        {
            _launchedProcess.Dispose();
            _launchedProcess = null;
        }
    }
}
