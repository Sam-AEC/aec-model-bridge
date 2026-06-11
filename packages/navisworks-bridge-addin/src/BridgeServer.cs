using System;
using System.IO;
using System.Net;
using System.Threading.Tasks;
using System.Windows.Threading;
using Autodesk.Navisworks.Api;
using Application = Autodesk.Navisworks.Api.Application;

namespace NavisworksBridge
{
    public class BridgeServer
    {
        private HttpListener? _listener;
        private bool _isRunning;
        private readonly Dispatcher _dispatcher;

        public BridgeServer(Dispatcher dispatcher)
        {
            _dispatcher = dispatcher;
        }

        public void Start()
        {
            _listener = new HttpListener();
            _listener.Prefixes.Add("http://127.0.0.1:3002/");
            _listener.Start();
            _isRunning = true;
            Task.Run(ListenAsync);
        }

        public void Stop()
        {
            _isRunning = false;
            _listener?.Stop();
        }

        private async Task ListenAsync()
        {
            while (_isRunning && _listener != null && _listener.IsListening)
            {
                try
                {
                    var context = await _listener.GetContextAsync();
                    ProcessRequest(context);
                }
                catch (Exception)
                {
                    // Listener stopped or error
                }
            }
        }

        private void ProcessRequest(HttpListenerContext context)
        {
            if (context.Request.Url.AbsolutePath == "/health")
            {
                SendJsonResponse(context, "{\"status\":\"healthy\",\"application\":\"navisworks\"}");
                return;
            }

            if (context.Request.Url.AbsolutePath == "/execute" && context.Request.HttpMethod == "POST")
            {
                using var reader = new StreamReader(context.Request.InputStream, context.Request.ContentEncoding);
                var requestBody = reader.ReadToEnd();

                _dispatcher.Invoke(() =>
                {
                    try
                    {
                        var doc = Application.ActiveDocument;
                        // For now, just return active document title as proof of concept
                        string title = doc.Title?.Replace("\"", "\\\"") ?? "";
                        string fileName = doc.FileName?.Replace("\"", "\\\"") ?? "";
                        string jsonResponse = "{\"status\":\"success\",\"title\":\"" + title + "\",\"fileName\":\"" + fileName + "\",\"modelsCount\":" + doc.Models.Count + "}";
                        SendJsonResponse(context, jsonResponse);
                    }
                    catch (Exception ex)
                    {
                        string errMsg = ex.Message.Replace("\"", "\\\"");
                        SendJsonResponse(context, "{\"status\":\"error\",\"message\":\"" + errMsg + "\"}");
                    }
                });
                return;
            }

            // Not found
            context.Response.StatusCode = 404;
            context.Response.Close();
        }

        private void SendJsonResponse(HttpListenerContext context, string json)
        {
            byte[] buffer = System.Text.Encoding.UTF8.GetBytes(json);
            context.Response.ContentType = "application/json";
            context.Response.ContentLength64 = buffer.Length;
            context.Response.OutputStream.Write(buffer, 0, buffer.Length);
            context.Response.OutputStream.Close();
        }
    }
}
