using System;
using System.IO;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Rhino;

namespace RhinoBridge
{
    public class BridgeServer
    {
        private readonly HttpListener _listener;
        private CancellationTokenSource _cts = new();
        private Task? _listenerTask;

        public BridgeServer(int port)
        {
            Port = port;
            _listener = new HttpListener();
            _listener.Prefixes.Add($"http://127.0.0.1:{Port}/");
            _listener.Prefixes.Add($"http://localhost:{Port}/");
        }

        public int Port { get; private set; }
        public bool IsListening { get; private set; }

        public void Start()
        {
            if (IsListening) return;
            try
            {
                _listener.Start();
                IsListening = true;
                _cts = new CancellationTokenSource();
                _listenerTask = Task.Run(() => ListenLoop(_cts.Token));
            }
            catch (Exception ex)
            {
                RhinoApp.WriteLine($"Failed to start HTTP listener on port {Port}: {ex.Message}");
            }
        }

        public void Stop()
        {
            if (!IsListening) return;
            IsListening = false;
            _cts.Cancel();
            _listener.Stop();
            try { _listenerTask?.Wait(2000); } catch { }
        }

        private async Task ListenLoop(CancellationToken token)
        {
            while (!token.IsCancellationRequested && _listener.IsListening)
            {
                try
                {
                    var context = await _listener.GetContextAsync().ConfigureAwait(false);
                    _ = Task.Run(() => HandleRequestAsync(context), token);
                }
                catch (HttpListenerException) { break; }
                catch (OperationCanceledException) { break; }
                catch (Exception) { /* log error */ }
            }
        }

        private async Task HandleRequestAsync(HttpListenerContext context)
        {
            var request = context.Request;
            var response = context.Response;

            // CORS headers
            response.Headers.Add("Access-Control-Allow-Origin", "*");
            response.Headers.Add("Access-Control-Allow-Methods", "POST, GET, OPTIONS");
            response.Headers.Add("Access-Control-Allow-Headers", "Content-Type");

            if (request.HttpMethod == "OPTIONS")
            {
                response.StatusCode = 200;
                response.Close();
                return;
            }

            try
            {
                string resultJson;

                if (request.Url?.AbsolutePath == "/health" && request.HttpMethod == "GET")
                {
                    resultJson = JsonSerializer.Serialize(new { status = "healthy", bridge = "Rhino Bridge Addin", port = Port });
                }
                else if (request.Url?.AbsolutePath == "/execute" && request.HttpMethod == "POST")
                {
                    using var reader = new StreamReader(request.InputStream, request.ContentEncoding ?? Encoding.UTF8);
                    var body = await reader.ReadToEndAsync();

                    var tcs = new TaskCompletionSource<string>();
                    
                    // Execute on Rhino main thread
                    RhinoApp.InvokeOnUiThread((Action)(() =>
                    {
                        try
                        {
                            var result = BridgeCommands.ExecuteCommand(body);
                            tcs.SetResult(result);
                        }
                        catch (Exception ex)
                        {
                            tcs.SetException(ex);
                        }
                    }));

                    resultJson = await tcs.Task;
                }
                else
                {
                    response.StatusCode = 404;
                    resultJson = JsonSerializer.Serialize(new { error = "Not found" });
                }

                var buffer = Encoding.UTF8.GetBytes(resultJson);
                response.ContentType = "application/json";
                response.ContentLength64 = buffer.Length;
                await response.OutputStream.WriteAsync(buffer, 0, buffer.Length);
            }
            catch (Exception ex)
            {
                response.StatusCode = 500;
                var errBuffer = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(new { error = ex.Message }));
                try { await response.OutputStream.WriteAsync(errBuffer, 0, errBuffer.Length); } catch { }
            }
            finally
            {
                response.Close();
            }
        }
    }
}
