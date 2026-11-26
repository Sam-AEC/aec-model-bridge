using System;
using System.IO;
using System.IO.Pipes;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Autodesk.Revit.UI;
using Serilog;

namespace RevitBridge.Bridge;

/// <summary>
/// Opt-in named-pipe transport (ADR 0021). Started only when AEC_BRIDGE_TRANSPORT=pipe; the HTTP
/// listener keeps running beside it. The pipe ACL allows only the current Windows user.
///
/// One request per connection. Frame: 4-byte little-endian length, then UTF-8 JSON.
/// Request:  {"method": "GET"|"POST", "path": "/execute", "headers": {"Authorization": "Bearer ..."}, "body": {...}}
/// Response: {"status": 200, "body": {...}}
/// The body JSON, the bearer token rule and the routes match the HTTP listener. Requests go into
/// the same CommandQueue and run on the Revit UI thread through the same ExternalEvent.
/// UNVERIFIED in live Revit and unbuilt in CI.
/// </summary>
public sealed class PipeBridgeServer
{
    public const string TransportVariable = "AEC_BRIDGE_TRANSPORT";
    public const int MaxRequestFrameBytes = PipeFraming.MaxRequestFrameBytes;
    public const int MaxResponseFrameBytes = PipeFraming.MaxResponseFrameBytes;
    private const int MaxInstances = 4;
    private const int BufferSize = 64 * 1024;
    private const int ReadTimeoutMs = 10000;
    private const int MaxWaitMs = 55000;
    private static readonly int SoftWaitMs = EnvMs("AEC_BRIDGE_SOFT_WAIT_MS", 25000);

    private readonly BridgeServer _owner;
    private readonly ExternalEvent _externalEvent;
    private readonly WorkspaceMonitor _workspaceMonitor = new();
    private readonly SemaphoreSlim _slots = new(MaxInstances, MaxInstances);
    private readonly PipeSecurity _security;
    private CancellationTokenSource _cts = new();
    private NamedPipeServerStream? _waiting;

    public PipeBridgeServer(BridgeServer owner, ExternalEvent externalEvent)
    {
        _owner = owner;
        _externalEvent = externalEvent;
        _security = CurrentUserOnly();
        PipeName = NewPipeName(System.Diagnostics.Process.GetCurrentProcess().Id);
    }

    /// <summary>Name without the \\.\pipe\ prefix. Random per Revit process, published in the registry entry.</summary>
    public string PipeName { get; }
    public bool IsListening { get; private set; }

    public static bool IsRequested()
    {
        var value = Environment.GetEnvironmentVariable(TransportVariable);
        return value != null && string.Equals(value.Trim(), "pipe", StringComparison.OrdinalIgnoreCase);
    }

    public static string NewPipeName(int pid)
    {
        return "AECModelBridge-revit-" + pid + "-" + Guid.NewGuid().ToString("N");
    }

    private static int EnvMs(string name, int fallback)
    {
        return int.TryParse(Environment.GetEnvironmentVariable(name), out var value)
            ? Math.Min(MaxWaitMs, Math.Max(1000, value))
            : fallback;
    }

    /// <summary>DACL with one entry: full control for the current user. Inherited entries are removed.</summary>
    private static PipeSecurity CurrentUserOnly()
    {
        using var identity = WindowsIdentity.GetCurrent();
        var user = identity.User
            ?? throw new InvalidOperationException("The current Windows user has no SID.");
        var security = new PipeSecurity();
        security.SetAccessRuleProtection(true, false);
        security.AddAccessRule(new PipeAccessRule(user, PipeAccessRights.FullControl, AccessControlType.Allow));
        return security;
    }

    private NamedPipeServerStream CreateInstance()
    {
#if NETFRAMEWORK
        return new NamedPipeServerStream(PipeName, PipeDirection.InOut, MaxInstances, PipeTransmissionMode.Byte,
            PipeOptions.Asynchronous, BufferSize, BufferSize, _security);
#else
        return NamedPipeServerStreamAcl.Create(PipeName, PipeDirection.InOut, MaxInstances, PipeTransmissionMode.Byte,
            PipeOptions.Asynchronous, BufferSize, BufferSize, _security);
#endif
    }

    /// <summary>Creates the first pipe instance before returning, so the caller publishes the name only for a pipe that exists.</summary>
    public bool Start()
    {
        if (IsListening) return true;
        try
        {
            if (_cts.IsCancellationRequested) _cts = new CancellationTokenSource();
            _slots.Wait();
            NamedPipeServerStream first;
            try
            {
                first = CreateInstance();
            }
            catch
            {
                _slots.Release();
                throw;
            }
            IsListening = true;
            var token = _cts.Token;
            _ = Task.Run(() => AcceptLoop(first, token));
            Log.Information("Named-pipe bridge listening on {PipeName} (current user only)", PipeName);
            return true;
        }
        catch (Exception ex)
        {
            Log.Error(ex, "Failed to start the named-pipe bridge; HTTP stays available");
            IsListening = false;
            return false;
        }
    }

    public void Stop()
    {
        if (!IsListening) return;
        IsListening = false;
        try
        {
            _cts.Cancel();
            Interlocked.Exchange(ref _waiting, null)?.Dispose();
            Log.Information("Named-pipe bridge stopped");
        }
        catch (Exception ex)
        {
            Log.Error(ex, "Failed to stop the named-pipe bridge");
        }
    }

    private async Task AcceptLoop(NamedPipeServerStream first, CancellationToken token)
    {
        NamedPipeServerStream? next = first;
        while (!token.IsCancellationRequested)
        {
            var server = next;
            next = null;
            try
            {
                if (server == null)
                {
                    await _slots.WaitAsync(token).ConfigureAwait(false);
                    try
                    {
                        server = CreateInstance();
                    }
                    catch
                    {
                        _slots.Release();
                        throw;
                    }
                }
                Volatile.Write(ref _waiting, server);
                await server.WaitForConnectionAsync(token).ConfigureAwait(false);
                Interlocked.CompareExchange(ref _waiting, null, server);
                var connected = server;
                server = null;
                _ = Task.Run(() => HandleConnection(connected, token));
            }
            catch (OperationCanceledException)
            {
                ReleaseUnused(server);
                break;
            }
            catch (ObjectDisposedException) when (token.IsCancellationRequested)
            {
                ReleaseUnused(server);
                break;
            }
            catch (Exception ex)
            {
                ReleaseUnused(server);
                if (token.IsCancellationRequested) break;
                Log.Error(ex, "Named-pipe accept error");
                try { await Task.Delay(1000, token).ConfigureAwait(false); }
                catch (OperationCanceledException) { break; }
            }
        }
    }

    private void ReleaseUnused(NamedPipeServerStream? server)
    {
        if (server == null) return;
        Interlocked.CompareExchange(ref _waiting, null, server);
        try { server.Dispose(); } catch { }
        _slots.Release();
    }

    private async Task HandleConnection(NamedPipeServerStream pipe, CancellationToken token)
    {
        try
        {
            string reply;
            byte[]? frame = null;
            try
            {
                frame = await PipeFraming.ReadFrame(pipe, MaxRequestFrameBytes, ReadTimeoutMs, token).ConfigureAwait(false);
            }
            catch (InvalidDataException ex)
            {
                Log.Warning("Named-pipe request refused: {Message}", ex.Message);
                reply = Reply(413, JsonSerializer.Serialize(new { error = "Payload too large" }));
                await PipeFraming.WriteFrame(pipe, reply, token).ConfigureAwait(false);
                return;
            }
            if (frame == null) return; // client went away before sending a whole frame

            try
            {
                reply = await Dispatch(frame).ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                Log.Error(ex, "Named-pipe request handling error");
                reply = Reply(500, JsonSerializer.Serialize(new { error = ex.Message }));
            }
            if (Encoding.UTF8.GetByteCount(reply) > MaxResponseFrameBytes)
            {
                Log.Warning("Named-pipe response exceeds {Max} bytes; sent 500 instead", MaxResponseFrameBytes);
                reply = Reply(500, JsonSerializer.Serialize(new { error = "Response too large for the pipe transport; use HTTP or ask for a smaller page." }));
            }
            await PipeFraming.WriteFrame(pipe, reply, token).ConfigureAwait(false);
            await WaitForClientClose(pipe).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is IOException || ex is OperationCanceledException || ex is ObjectDisposedException)
        {
            Log.Debug(ex, "Named-pipe connection ended early");
        }
        catch (Exception ex)
        {
            Log.Error(ex, "Named-pipe connection error");
        }
        finally
        {
            try { pipe.Dispose(); } catch { }
            _slots.Release();
        }
    }

    /// <summary>Disconnecting discards unread bytes, so give the client time to read the reply and close its end.</summary>
    private static async Task WaitForClientClose(Stream stream)
    {
        using var timeout = new CancellationTokenSource(ReadTimeoutMs);
        var probe = new byte[1];
        try
        {
            await stream.ReadAsync(probe, 0, 1, timeout.Token).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is IOException || ex is OperationCanceledException || ex is ObjectDisposedException)
        {
        }
    }

    private static string Reply(int status, string bodyJson)
    {
        return "{\"status\":" + status + ",\"body\":" + bodyJson + "}";
    }

    private static string ReplyObject(int status, object body)
    {
        return Reply(status, JsonSerializer.Serialize(body));
    }

    private async Task<string> Dispatch(byte[] frame)
    {
        using var doc = JsonDocument.Parse(new ReadOnlyMemory<byte>(frame));
        var root = doc.RootElement;
        if (root.ValueKind != JsonValueKind.Object)
            return ReplyObject(400, new { error = "Request must be a JSON object" });

        var method = root.TryGetProperty("method", out var m) && m.ValueKind == JsonValueKind.String ? m.GetString() ?? "" : "";
        var path = root.TryGetProperty("path", out var p) && p.ValueKind == JsonValueKind.String ? p.GetString() ?? "/" : "/";
        string? auth = null;
        if (root.TryGetProperty("headers", out var headers) && headers.ValueKind == JsonValueKind.Object
            && headers.TryGetProperty("Authorization", out var a) && a.ValueKind == JsonValueKind.String)
        {
            auth = a.GetString();
        }

        // Same rule as HTTP: every route except /health needs the session token. The pipe has no legacy mode.
        if (path != "/health" && !PipeFraming.TokenMatches(auth, "Bearer " + _owner.SessionToken))
            return ReplyObject(401, new { error = "Unauthorized" });

        if (path == "/health") return Health();
        if (path == "/tools") return ReplyObject(200, new { tools = BridgeCommandFactory.GetToolCatalog() });
        if (path == "/capabilities") return ReplyObject(200, new { tools = BridgeCommandFactory.GetCapabilities() });
        if (path == "/execute" && method == "POST")
        {
            if (!root.TryGetProperty("body", out var body) || body.ValueKind != JsonValueKind.Object)
                return ReplyObject(400, new { error = "POST /execute needs a JSON object body" });
            return await Execute(body.Clone()).ConfigureAwait(false);
        }
        if (path.StartsWith("/result/", StringComparison.Ordinal) && method == "GET")
            return Result(Uri.UnescapeDataString(path.Substring("/result/".Length)));
        return ReplyObject(404, new { error = "Not found" });
    }

    private string Health()
    {
        var queue = _owner.Queue;
        var running = queue.GetRunning();
        return ReplyObject(200, new
        {
            status = "healthy",
            transport = "pipe",
            version = System.Reflection.Assembly.GetExecutingAssembly().GetName().Version?.ToString(),
            uptime_seconds = _owner.UptimeSeconds,
            revit_version = App.RevitVersion ?? "unknown",
            active_document = App.ActiveDocumentName ?? "none",
            build = ProductInfo.BuildInfo,
            queue_depth = queue.Count,
            retained_results = queue.FinishedCount,
            running = running == null
                ? null
                : new { request_id = running.RequestId, tool = running.Tool, age_ms = running.ElapsedMs }
        });
    }

    private async Task<string> Execute(JsonElement root)
    {
        var startTime = DateTime.UtcNow;
        var requestId = root.GetProperty("request_id").GetString() ?? Guid.NewGuid().ToString();
        var tool = root.GetProperty("tool").GetString() ?? string.Empty;
        var payload = root.GetProperty("payload");

        try
        {
            PayloadPathValidator.Validate(payload, _workspaceMonitor.AssertInWorkspace);
        }
        catch (UnauthorizedAccessException ex)
        {
            Log.Warning("Workspace violation in pipe request {RequestId} {Tool}: {Message}", requestId, tool, ex.Message);
            return ReplyObject(403, new { error = "Workspace violation: " + ex.Message });
        }

        var queue = _owner.Queue;
        Log.Information("Pipe request received: {RequestId} {Tool}", requestId, tool);
        queue.Enqueue(new CommandRequest { RequestId = requestId, Tool = tool, Payload = payload });
        _externalEvent.Raise();

        var waitMs = SoftWaitMs;
        if (root.TryGetProperty("wait_ms", out var waitProp) && waitProp.ValueKind == JsonValueKind.Number && waitProp.TryGetInt32(out var asked))
        {
            waitMs = Math.Min(MaxWaitMs, Math.Max(0, asked));
        }

        var snapshot = await queue.WaitForResponse(requestId, waitMs).ConfigureAwait(false);
        if (snapshot != null && snapshot.IsFinished && snapshot.ResponseJson != null)
        {
            Log.Information("Pipe request completed: {RequestId} {Tool} {State} {DurationMs}ms",
                requestId, tool, snapshot.State, (DateTime.UtcNow - startTime).TotalMilliseconds);
            return Reply(200, snapshot.ResponseJson);
        }

        return ReplyObject(200, new
        {
            status = "running",
            state = snapshot?.State ?? "running",
            request_id = requestId,
            tool,
            elapsed_ms = snapshot?.ElapsedMs ?? 0,
            message = $"Request {requestId} is still {snapshot?.State ?? "running"} in Revit; fetch it with GET /result/{requestId}"
        });
    }

    private string Result(string requestId)
    {
        var queue = _owner.Queue;
        var snapshot = queue.GetSnapshot(requestId);
        if (snapshot == null)
            return ReplyObject(404, new { error = "unknown_or_expired", request_id = requestId });

        var json = "{\"request_id\":" + JsonSerializer.Serialize(snapshot.RequestId)
            + ",\"tool\":" + JsonSerializer.Serialize(snapshot.Tool)
            + ",\"state\":" + JsonSerializer.Serialize(snapshot.State)
            + ",\"elapsed_ms\":" + snapshot.ElapsedMs
            + ",\"ttl_seconds\":" + (int)queue.ResultTtl.TotalSeconds
            + ",\"response\":" + (snapshot.ResponseJson ?? "null")
            + "}";
        return Reply(200, json);
    }
}
