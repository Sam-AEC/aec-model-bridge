using System;
using System.IO;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Threading;

namespace NavisworksBridge
{
    public class BridgeServer
    {
        private readonly HttpListener _listener;
        private readonly Dispatcher _dispatcher;
        private CancellationTokenSource _cts = new();
        private readonly DateTime _startTime = DateTime.UtcNow;
        private Task? _listenerTask;
        private int _totalRequests = 0;
        private int _activeConnections = 0;
        private SemaphoreSlim _concurrencySemaphore = new(10, 10);
        private const long MaxRequestSizeBytes = 5 * 1024 * 1024; // 5 MB

        public BridgeServer(Dispatcher dispatcher)
        {
            _dispatcher = dispatcher;
            _listener = new HttpListener();
            SessionToken = Guid.NewGuid().ToString("N") + Guid.NewGuid().ToString("N");
            
            var legacyEnv = Environment.GetEnvironmentVariable("MCP_NAVISWORKS_LEGACY_PORT");
            LegacyMode = string.IsNullOrEmpty(legacyEnv) || legacyEnv.ToLower() == "true" || legacyEnv == "1";
        }

        public string SessionToken { get; }
        public int Port { get; private set; }
        public string RegistryFilePath { get; private set; }
        public bool LegacyMode { get; }

        public bool IsListening { get; private set; }
        public bool IsRunning => IsListening;
        public int ActiveConnections => _activeConnections;
        public int TotalRequests => _totalRequests;
        public double UptimeSeconds => (DateTime.UtcNow - _startTime).TotalSeconds;

        public void Start()
        {
            if (IsListening) return;

            try
            {
                if (_cts.IsCancellationRequested)
                    _cts = new CancellationTokenSource();

                if (LegacyMode)
                {
                    Port = 3002;
                }
                else
                {
                    var tcp = new System.Net.Sockets.TcpListener(IPAddress.Loopback, 0);
                    tcp.Start();
                    Port = ((IPEndPoint)tcp.LocalEndpoint).Port;
                    tcp.Stop();
                }

                var prefix = $"http://127.0.0.1:{Port}/";
                _listener.Prefixes.Clear();
                _listener.Prefixes.Add(prefix);

                _listener.Start();
                _listenerTask = Task.Run(ListenerLoop, _cts.Token);
                IsListening = true;

                WriteRegistryFile(prefix);
            }
            catch (Exception ex)
            {
                 IsListening = false;
                 throw new InvalidOperationException("Failed to start listener", ex);
            }
        }

        public void Stop()
        {
            if (!IsListening) return;

            try
            {
                _cts.Cancel();
                _listener.Stop();
                IsListening = false;
                
                if (!string.IsNullOrEmpty(RegistryFilePath) && File.Exists(RegistryFilePath))
                {
                    try { File.Delete(RegistryFilePath); } catch { }
                }
            }
            catch (Exception)
            {
                // ignore
            }
        }

        private async Task ListenerLoop()
        {
            while (!_cts.Token.IsCancellationRequested)
            {
                try
                {
                    var context = await _listener.GetContextAsync();
                    _ = Task.Run(() => HandleRequest(context), _cts.Token);
                }
                catch (HttpListenerException) when (_cts.Token.IsCancellationRequested)
                {
                    break;
                }
                catch (Exception)
                {
                    // ignore
                }
            }
        }

        private async Task HandleRequest(HttpListenerContext context)
        {
            Interlocked.Increment(ref _activeConnections);
            Interlocked.Increment(ref _totalRequests);

            try
            {
                await _concurrencySemaphore.WaitAsync(_cts.Token);
            }
            catch (OperationCanceledException)
            {
                Interlocked.Decrement(ref _activeConnections);
                return;
            }

            try
            {
                if (context.Request.ContentLength64 > MaxRequestSizeBytes)
                {
                    Respond(context, 413, new { error = "Payload too large" });
                    return;
                }

                var path = context.Request.Url?.AbsolutePath ?? "/";

                if (path == "/health")
                {
                    await HandleHealth(context);
                }
                else if (path == "/tools")
                {
                    await HandleTools(context);
                }
                else if (path == "/capabilities")
                {
                    await HandleCapabilities(context);
                }
                else if (path == "/execute" && context.Request.HttpMethod == "POST")
                {
                    await HandleExecute(context);
                }
                else
                {
                    Respond(context, 404, new { error = "Not found" });
                }
            }
            catch (Exception ex)
            {
                Respond(context, 500, new { error = ex.Message });
            }
            finally
            {
                _concurrencySemaphore.Release();
                Interlocked.Decrement(ref _activeConnections);
            }
        }

        private async Task HandleExecute(HttpListenerContext context)
        {
            if (!LegacyMode)
            {
                var authHeader = context.Request.Headers["Authorization"];
                if (string.IsNullOrEmpty(authHeader) || authHeader != $"Bearer {SessionToken}")
                {
                    Respond(context, 401, new { error = "Unauthorized" });
                    return;
                }
            }

            using var reader = new StreamReader(context.Request.InputStream);
            var body = await reader.ReadToEndAsync();
            var doc = JsonDocument.Parse(body);
            var root = doc.RootElement;

            var requestId = root.GetProperty("request_id").GetString() ?? Guid.NewGuid().ToString();
            var tool = root.GetProperty("tool").GetString() ?? string.Empty;
            var payload = root.TryGetProperty("payload", out var p) ? p : new JsonElement();

            object result = null;
            Exception error = null;

            // Execute on Main Thread
            await _dispatcher.InvokeAsync(() =>
            {
                try
                {
                    result = BridgeCommandFactory.Execute(tool, payload);
                }
                catch (Exception ex)
                {
                    error = ex;
                }
            });

            if (error != null)
            {
                Respond(context, 200, new
                {
                    ok = false,
                    request_id = requestId,
                    error_code = "execution_error",
                    message = error.Message
                });
            }
            else
            {
                Respond(context, 200, new
                {
                    ok = true,
                    request_id = requestId,
                    data = result,
                    warnings = System.Array.Empty<string>(),
                    artifacts = System.Array.Empty<object>(),
                    job = (object?)null
                });
            }
        }

        private Task HandleHealth(HttpListenerContext context)
        {
            var health = new
            {
                status = "healthy",
                version = System.Reflection.Assembly.GetExecutingAssembly().GetName().Version?.ToString(),
                uptime_seconds = (DateTime.UtcNow - _startTime).TotalSeconds,
            };
            Respond(context, 200, health);
            return Task.CompletedTask;
        }

        private Task HandleTools(HttpListenerContext context)
        {
            var tools = BridgeCommandFactory.GetToolCatalog();
            Respond(context, 200, new { tools });
            return Task.CompletedTask;
        }

        private Task HandleCapabilities(HttpListenerContext context)
        {
            var tools = BridgeCommandFactory.GetCapabilities();
            Respond(context, 200, new { tools });
            return Task.CompletedTask;
        }

        private void WriteRegistryFile(string endpoint)
        {
            try
            {
                int pid = System.Diagnostics.Process.GetCurrentProcess().Id;
                var registryDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AECModelBridge", "registry");
                Directory.CreateDirectory(registryDir);

                RegistryFilePath = Path.Combine(registryDir, $"navisworks-{pid}.json");

                var data = new
                {
                    provider_id = "navisworks",
                    endpoint = endpoint.TrimEnd('/'),
                    pid = pid,
                    host_version = "Navisworks",
                    connector_version = System.Reflection.Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "1.0",
                    protocol_version = 2,
                    capability_digest = "dynamic",
                    session_token = SessionToken,
                    started_at = _startTime.ToString("o")
                };

                var json = JsonSerializer.Serialize(data, new JsonSerializerOptions { WriteIndented = true });
                File.WriteAllText(RegistryFilePath, json);
            }
            catch (Exception)
            {
                // ignore
            }
        }

        private void Respond(HttpListenerContext context, int statusCode, object data)
        {
            context.Response.StatusCode = statusCode;
            context.Response.ContentType = "application/json";
            var json = JsonSerializer.Serialize(data);
            var buffer = Encoding.UTF8.GetBytes(json);
            context.Response.OutputStream.Write(buffer, 0, buffer.Length);
            context.Response.Close();
        }
    }
}
