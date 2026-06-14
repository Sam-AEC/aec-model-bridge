using System;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.AnalysisServices.AdomdClient;

namespace PowerBIBridge
{
    class Program
    {
        static async Task Main(string[] args)
        {
            Console.WriteLine("AEC Model Bridge - Power BI External Tool");

            if (args.Length < 2)
            {
                Console.WriteLine("Error: Missing Server and Database arguments. This tool must be launched from Power BI Desktop.");
                Console.WriteLine("Usage: PowerBIBridge.exe <server> <database>");
                Console.WriteLine("Press any key to exit...");
                Console.ReadKey();
                return;
            }

            string server = args[0];
            string database = args[1];

            Console.WriteLine($"Connected to local Power BI instance:");
            Console.WriteLine($"Server: {server}");
            Console.WriteLine($"Database: {database}");

            int port = 3006;
            var listener = new HttpListener();
            listener.Prefixes.Add($"http://127.0.0.1:{port}/");
            listener.Prefixes.Add($"http://localhost:{port}/");

            try
            {
                listener.Start();
                Console.WriteLine($"\nHTTP Bridge listening on port {port}...");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Failed to start HTTP listener: {ex.Message}");
                return;
            }

            var cts = new CancellationTokenSource();
            Console.CancelKeyPress += (s, e) =>
            {
                Console.WriteLine("Shutting down bridge...");
                cts.Cancel();
                e.Cancel = true;
            };

            while (!cts.IsCancellationRequested)
            {
                try
                {
                    var context = await listener.GetContextAsync();
                    _ = Task.Run(() => HandleRequest(context, server, database));
                }
                catch (HttpListenerException) { break; }
                catch (OperationCanceledException) { break; }
            }
        }

        static async Task HandleRequest(HttpListenerContext context, string server, string database)
        {
            var request = context.Request;
            var response = context.Response;

            response.Headers.Add("Access-Control-Allow-Origin", "*");
            response.Headers.Add("Access-Control-Allow-Methods", "POST, GET, OPTIONS");
            
            if (request.HttpMethod == "OPTIONS")
            {
                response.StatusCode = 200;
                response.Close();
                return;
            }

            try
            {
                string resultJson = "";

                if (request.Url?.AbsolutePath == "/health" && request.HttpMethod == "GET")
                {
                    resultJson = JsonSerializer.Serialize(new { status = "healthy", bridge = "Power BI External Tool", port = 3006 });
                }
                else if (request.Url?.AbsolutePath == "/execute" && request.HttpMethod == "POST")
                {
                    using var reader = new System.IO.StreamReader(request.InputStream, request.ContentEncoding ?? Encoding.UTF8);
                    var body = await reader.ReadToEndAsync();
                    
                    using var doc = JsonDocument.Parse(body);
                    var root = doc.RootElement;
                    string command = root.GetProperty("command").GetString() ?? "";

                    if (command == "execute_dax")
                    {
                        string query = root.GetProperty("query").GetString() ?? "";
                        resultJson = ExecuteDaxQuery(server, database, query);
                    }
                    else if (command == "invoke_method")
                    {
                        var className = root.GetProperty("class_name").GetString();
                        var methodName = root.GetProperty("method_name").GetString();
                        var args = root.GetProperty("arguments");
                        var targetId = root.TryGetProperty("target_id", out var tId) ? tId.GetString() : null;

                        var result = ReflectionHelper.InvokeMethod(className, methodName, args, targetId);
                        resultJson = JsonSerializer.Serialize(new { success = true, data = result });
                    }
                    else if (command == "reflect_get")
                    {
                        var targetId = root.GetProperty("target_id").GetString();
                        var propertyName = root.GetProperty("property_name").GetString();

                        var target = ReflectionHelper.GetObject(targetId);
                        if (target == null) throw new Exception($"Target '{targetId}' not found");

                        var prop = target.GetType().GetProperty(propertyName);
                        if (prop == null) throw new Exception($"Property '{propertyName}' not found on type '{target.GetType().Name}'");

                        var value = prop.GetValue(target);
                        if (value == null) resultJson = JsonSerializer.Serialize(new { success = true, data = (object)null });
                        else if (value.GetType().IsPrimitive || value is string) resultJson = JsonSerializer.Serialize(new { success = true, data = value });
                        else
                        {
                            var refId = ReflectionHelper.RegisterObject(value);
                            resultJson = JsonSerializer.Serialize(new { success = true, data = new { type = "reference", id = refId, class_name = value.GetType().Name, str = value.ToString() } });
                        }
                    }
                    else if (command == "reflect_set")
                    {
                        var targetId = root.GetProperty("target_id").GetString();
                        var propertyName = root.GetProperty("property_name").GetString();
                        var valueElement = root.GetProperty("value");

                        var target = ReflectionHelper.GetObject(targetId);
                        if (target == null) throw new Exception($"Target '{targetId}' not found");

                        var prop = target.GetType().GetProperty(propertyName);
                        if (prop == null) throw new Exception($"Property '{propertyName}' not found on type '{target.GetType().Name}'");

                        var value = ReflectionHelper.ParseArgument(valueElement);
                        if (value != null && !prop.PropertyType.IsAssignableFrom(value.GetType()))
                        {
                            value = Convert.ChangeType(value, prop.PropertyType);
                        }

                        prop.SetValue(target, value);
                        resultJson = JsonSerializer.Serialize(new { success = true, data = new { status = "success", target_id = targetId, property = propertyName } });
                    }
                    else
                    {
                        response.StatusCode = 404;
                        resultJson = JsonSerializer.Serialize(new { error = $"Unknown command: {command}" });
                    }
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

        static string ExecuteDaxQuery(string server, string database, string query)
        {
            string connectionString = $"Data Source={server};Initial Catalog={database};";
            using var connection = new AdomdConnection(connectionString);
            connection.Open();

            using var cmd = connection.CreateCommand();
            cmd.CommandText = query;
            
            using var reader = cmd.ExecuteReader();
            
            var results = new System.Collections.Generic.List<System.Collections.Generic.Dictionary<string, object>>();
            while (reader.Read())
            {
                var row = new System.Collections.Generic.Dictionary<string, object>();
                for (int i = 0; i < reader.FieldCount; i++)
                {
                    row[reader.GetName(i)] = reader.GetValue(i);
                }
                results.Add(row);
            }

            return JsonSerializer.Serialize(new { success = true, data = results });
        }
    }
}
